"""Native image response/cache contracts, independent of image file decoding."""

import copy
import json

import httpx2
import pytest

from systemoneprompts.answers import is_answer_shape, is_box_coordinates
from systemoneprompts.cache import FetchResponse, cache_stats, clear_cache, create_caching_fetch
from systemoneprompts.client import BoxCoordinates, TypeSafeClient, TypeSafeClientError

BOX = {
    "type": "box",
    "box": {"top": 0.1, "bottom": 0.9, "left": 0.2, "right": 0.8},
    "confidence": None,
}
REQUEST = {"state": {}, "questions": {"q": {"type": "box"}}, "model": "jev-1.14.0"}
HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}
OPTIONS = {"method": "POST", "headers": HEADERS, "body": json.dumps(REQUEST)}
ENDPOINT = "https://native.example/v1/systemone"


def result():
    return {
        "model": "jev-reported",
        "answers": {"q": copy.deepcopy(BOX)},
        "usage": {"input_tokens": 2, "output_tokens": 1},
    }


def test_exact_box_geometry_and_nullable_confidence():
    assert is_answer_shape(BOX)
    for confidence in [-1, 2, "0.5", float("inf")]:
        assert not is_answer_shape({**BOX, "confidence": confidence})
    for coordinates in [
        {**BOX["box"], "extra": 3},
        {**BOX["box"], "top": 0.9},
        {**BOX["box"], "left": -0.1},
    ]:
        assert not is_box_coordinates(coordinates)
        with pytest.raises(ValueError):
            BoxCoordinates.model_validate(coordinates)


MALFORMED = [
    lambda r: {**r, "answers": {"q": {**BOX, "confidence": -1}}},
    lambda r: {**r, "answers": {"q": {**BOX, "confidence": 2}}},
    lambda r: {**r, "answers": {"q": {**BOX, "box": {**BOX["box"], "extra": 3}}}},
    lambda r: {**r, "usage": {"input_tokens": "bad", "output_tokens": 1}},
    lambda r: {**r, "usage": {"input_tokens": 1, "output_tokens": -1}},
    lambda r: {"model": r["model"], "answers": r["answers"]},
    lambda r: {**r, "answers": {}},
    lambda r: {**r, "answers": {**r["answers"], "extra": BOX}},
    lambda r: {**r, "answers": {"q": {"type": "noul", "noul": 1}}},
    lambda r: {**r, "model": " "},
]


@pytest.mark.parametrize("mutate", MALFORMED)
def test_malformed_live_image_response_is_never_cached(tmp_path, mutate):
    response = mutate(result())
    calls = []

    def network(url, options):
        calls.append(url)
        return FetchResponse(status=200, body=json.dumps(response).encode())

    caching = create_caching_fetch(dir=str(tmp_path), fetch=network)
    for _ in range(2):
        caching(ENDPOINT, OPTIONS)
    assert len(calls) == 2
    assert not list(tmp_path.rglob("*.json"))

    class Http:
        def request(self, *args, **kwargs):
            return httpx2.Response(200, json=response)

    client = TypeSafeClient(http_client=Http(), environ={}, max_retries=0)
    with pytest.raises(
        TypeSafeClientError, match="invalid System One response: image/Box contract"
    ):
        client.system_one_sync(**REQUEST, headers=HEADERS)


def test_cache_revalidates_disk_and_accepts_legacy_metadata(tmp_path):
    calls = []

    def network(url, options):
        calls.append(url)
        return FetchResponse(status=200, body=json.dumps(result()).encode())

    caching = create_caching_fetch(dir=str(tmp_path), fetch=network)
    caching(ENDPOINT, OPTIONS)
    path = next(tmp_path.rglob("*.json"))
    record = json.loads(path.read_text())
    del record["requestedModel"]
    path.write_text(json.dumps(record))
    assert caching(ENDPOINT, OPTIONS).json()["usage"] == {"input_tokens": 0, "output_tokens": 0}
    assert len(calls) == 1
    assert cache_stats(str(tmp_path)) == {"entries": 1, "models": {"jev-reported": 1}, "drift": []}
    for mutate in MALFORMED:
        damaged = {
            key: value for key, value in record.items() if key not in {"model", "answers", "usage"}
        }
        damaged.update(mutate(result()))
        path.write_text(json.dumps(damaged))
        previous = len(calls)
        caching(ENDPOINT, OPTIONS)
        assert len(calls) == previous + 1


def test_disk_stats_count_records_and_clear_preserves_siblings(tmp_path):
    directory = tmp_path / "cache"

    def network(url, options):
        request = json.loads(options["body"])
        value = (
            result()
            if request["questions"]["q"]["type"] == "box"
            else {
                "model": "text-reported",
                "answers": {"q": {"type": "noul", "noul": 1}},
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )
        if request["questions"]["q"]["type"] == "box":
            value["answers"]["second"] = {"type": "noul", "noul": 1}
        return FetchResponse(status=200, body=json.dumps(value).encode())

    caching = create_caching_fetch(dir=str(directory), fetch=network)
    image_request = {**REQUEST, "questions": {**REQUEST["questions"], "second": {"type": "noul"}}}
    caching(ENDPOINT, {**OPTIONS, "body": json.dumps(image_request)})
    text = {"state": {}, "questions": {"q": {"type": "noul"}}, "model": "text-requested"}
    caching(ENDPOINT, {**OPTIONS, "body": json.dumps(text)})
    stats = cache_stats(str(directory))
    assert stats["entries"] == 2
    assert stats["models"] == {"jev-reported": 1, "text-reported": 1}
    assert {"requested": "jev-1.14.0", "reported": "jev-reported", "count": 1} in stats["drift"]
    sibling = tmp_path / "keep.txt"
    sibling.write_text("keep")
    clear_cache(str(directory), root=str(tmp_path))
    assert not directory.exists()
    assert sibling.read_text() == "keep"


@pytest.mark.parametrize(
    "endpoint", ["https://openrouter.ai/api/alpha/decisions", "https://unknown.example/other"]
)
def test_bare_image_cache_rejects_unsupported_routes(tmp_path, endpoint):
    calls = []

    def network(url, options):
        calls.append(url)
        return FetchResponse(status=200, body=json.dumps(result()).encode())

    caching = create_caching_fetch(dir=str(tmp_path), fetch=network)
    with pytest.raises(Exception, match="native TypeSafe only"):
        caching(endpoint, OPTIONS)
    assert not calls
    assert not list(tmp_path.rglob("*.json"))


def test_bare_image_cache_rejects_legacy_cloudflare(tmp_path):
    calls = []

    def network(url, options):
        calls.append(url)
        return FetchResponse(status=200, body=json.dumps(result()).encode())

    network.systemoneprompts_cloudflare = True
    with pytest.raises(Exception, match="native TypeSafe only"):
        create_caching_fetch(dir=str(tmp_path), fetch=network)(ENDPOINT, OPTIONS)
    assert not calls
    assert not list(tmp_path.rglob("*.json"))
