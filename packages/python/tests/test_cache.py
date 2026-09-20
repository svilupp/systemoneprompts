from __future__ import annotations

import json
from pathlib import Path

import pytest

from systemoneprompts.cache import (
    CacheMissError,
    FetchResponse,
    cache_stats,
    clear_cache,
    create_caching_fetch,
    question_hash,
)

ENDPOINT = "https://api.typesafe.ai/v1/systemone"


def mock_fetch(handler):
    calls = {"n": 0}

    def fetch(_url: str, init: dict | None = None) -> FetchResponse:
        calls["n"] += 1
        body = json.loads(str((init or {}).get("body")))
        payload = handler(body)
        return FetchResponse(
            status=200,
            body=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
        )

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def request(questions: dict[str, object]) -> dict[str, str]:
    return {
        "method": "POST",
        "body": json.dumps({"model": "jev-latest", "state": {"ticket": "hi"}, "questions": questions}),
    }


def test_hash_is_stable_under_key_order() -> None:
    left = question_hash(
        {
            "model": "jev-latest",
            "state": {"b": 1, "a": 2},
            "question": {"type": "noul", "instructions": "x", "extra": False},
        }
    )
    right = question_hash(
        {
            "question": {"extra": False, "type": "noul", "instructions": "x"},
            "state": {"a": 2, "b": 1},
            "model": "jev-latest",
        }
    )
    assert left == right


def test_per_question_invalidation_and_usage(tmp_path: Path) -> None:
    def handler(body: dict[str, object]) -> dict[str, object]:
        questions = body["questions"]
        answers = {qid: {"type": "noul", "noul": 0.9} for qid in questions}  # type: ignore[union-attr]
        return {
            "model": "jev-2026-06",
            "answers": answers,
            "usage": {"input_tokens": 10 * len(questions), "output_tokens": 2},  # type: ignore[arg-type]
        }

    fetch = mock_fetch(handler)
    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    a = {"type": "noul", "instructions": "A?"}
    b = {"type": "noul", "instructions": "B?"}
    b_changed = {"type": "noul", "instructions": "B changed?"}

    first = cached(ENDPOINT, request({"a": a, "b": b})).json()
    assert first["usage"]["input_tokens"] == 20
    stats = cached.stats()
    assert (stats.requests, stats.hits, stats.misses) == (1, 0, 2)
    assert stats.keys == ["a", "b"]

    digest = question_hash({"model": "jev-latest", "state": {"ticket": "hi"}, "question": a})
    shard = tmp_path / digest[:2]
    assert any(path.suffix == ".json" for path in shard.iterdir())

    second = cached(ENDPOINT, request({"a": a, "b": b_changed})).json()
    assert second["usage"]["input_tokens"] == 10
    assert second["answers"]["a"] == {"type": "noul", "noul": 0.9}
    stats = cached.stats()
    assert stats.requests == 2
    assert stats.hits == 1
    assert stats.misses == 3
    assert fetch.calls["n"] == 2

    third = cached(ENDPOINT, request({"a": a, "b": b_changed})).json()
    assert third["usage"]["input_tokens"] == 0
    assert third["model"] == "jev-2026-06"
    stats = cached.stats()
    assert (stats.requests, stats.hits, stats.misses) == (3, 3, 3)
    assert fetch.calls["n"] == 2


def test_forwards_malformed_json_bodies(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fetch(_url: str, init: dict | None = None) -> FetchResponse:
        seen["body"] = (init or {}).get("body")
        return FetchResponse(status=200, body=b"forwarded")

    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    init = {"method": "POST", "body": "{not-json"}
    response = cached(ENDPOINT, init)
    assert seen["body"] == init["body"]
    assert response.text() == "forwarded"


def test_prototype_looking_ids(tmp_path: Path) -> None:
    fetch = mock_fetch(
        lambda body: {
            "model": "jev-latest",
            "answers": {
                qid: {"type": "noul", "noul": 0.9} for qid in body["questions"]  # type: ignore[union-attr]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )
    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    questions = {"__proto__": {"type": "noul", "instructions": "A?"}}
    first = cached(ENDPOINT, request(questions)).json()
    second = cached(ENDPOINT, request(questions)).json()
    assert first["answers"]["__proto__"] == {"type": "noul", "noul": 0.9}
    assert second["answers"]["__proto__"] == {"type": "noul", "noul": 0.9}
    assert fetch.calls["n"] == 1


def test_corrupt_records_are_read_only_misses(tmp_path: Path) -> None:
    question = {"type": "noul", "instructions": "A?"}
    state = {"ticket": "hi"}
    digest = question_hash({"model": "jev-latest", "state": state, "question": question})
    records = [
        None,
        [],
        "not-an-entry",
        {"hash": "0" * 64, "reportedModel": "jev-latest", "answer": {"type": "noul", "noul": 0.9}},
        {"hash": digest, "reportedModel": "jev-latest"},
        {"hash": digest, "reportedModel": "jev-latest", "answer": None},
        {"hash": digest, "reportedModel": "jev-latest", "answer": {}},
    ]
    for record in records:
        directory = tmp_path / str(id(record))
        shard = directory / digest[:2]
        shard.mkdir(parents=True)
        (shard / f"{digest}.json").write_text(json.dumps(record), encoding="utf-8")
        cached = create_caching_fetch(
            dir=str(directory),
            mode="read-only",
            fetch=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network")),
        )
        with pytest.raises(RuntimeError, match="cache miss in read-only mode") as info:
            cached(
                ENDPOINT,
                {
                    "method": "POST",
                    "body": json.dumps({"model": "jev-latest", "state": state, "questions": {"a": question}}),
                },
            )
        assert isinstance(info.value, CacheMissError)
        assert info.value.ids == ["a"]


def test_does_not_cache_malformed_successful_responses(tmp_path: Path) -> None:
    calls = {"n": 0}

    def fetch(_url: str, _init: dict | None = None) -> FetchResponse:
        calls["n"] += 1
        return FetchResponse(
            status=200,
            body=json.dumps(
                {
                    "model": "jev-latest",
                    "answers": {"a": {"type": "choice", "choice": "wrong", "confidence": 0.9}},
                }
            ).encode("utf-8"),
            headers={"x-typesafe-request-id": "req_bad"},
        )

    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    init = request({"a": {"type": "noul", "instructions": "A?"}})
    first = cached(ENDPOINT, init)
    second = cached(ENDPOINT, init)
    assert first.headers.get("x-typesafe-request-id") == "req_bad"
    assert second.headers.get("x-typesafe-request-id") == "req_bad"
    assert calls["n"] == 2


def test_merges_cached_hits_with_validated_live_answers(tmp_path: Path) -> None:
    calls = {"n": 0}

    def fetch(_url: str, init: dict | None = None) -> FetchResponse:
        calls["n"] += 1
        body = json.loads(str((init or {}).get("body")))
        if calls["n"] == 1:
            return FetchResponse(
                status=200,
                body=json.dumps(
                    {
                        "model": "jev-2026-06",
                        "answers": {"cached": {"type": "noul", "noul": 0.8}},
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    }
                ).encode("utf-8"),
            )
        assert list(body["questions"]) == ["live", "invalid", "missing"]
        return FetchResponse(
            status=207,
            status_text="Multi-Status",
            headers={"x-typesafe-request-id": "req_partial"},
            body=json.dumps(
                {
                    "model": "jev-2026-06",
                    "answers": {
                        "live": {"type": "noul", "noul": 0.7},
                        "invalid": {
                            "type": "choice",
                            "choice": "wrong",
                            "confidence": 0.9,
                            "probabilities": {"billing": 1, "orders": 0},
                        },
                    },
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                }
            ).encode("utf-8"),
        )

    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    cached_q = {"type": "noul", "instructions": "cached?"}
    live = {"type": "noul", "instructions": "live?"}
    invalid = {
        "type": "choice",
        "instructions": "invalid?",
        "criteria": {"billing": "Billing", "orders": "Orders"},
    }
    missing = {"type": "noul", "instructions": "missing?"}
    cached(ENDPOINT, request({"cached": cached_q}))
    response = cached(ENDPOINT, request({"cached": cached_q, "live": live, "invalid": invalid, "missing": missing}))
    body = response.json()
    assert response.status == 207
    assert response.status_text == "Multi-Status"
    assert response.headers.get("x-typesafe-request-id") == "req_partial"
    assert body["answers"] == {
        "cached": {"type": "noul", "noul": 0.8},
        "live": {"type": "noul", "noul": 0.7},
    }
    before = calls["n"]
    replay = cached(ENDPOINT, request({"cached": cached_q, "live": live})).json()
    assert replay["answers"] == body["answers"]
    assert calls["n"] == before


def test_validates_choice_and_score_against_criteria(tmp_path: Path) -> None:
    fetch = mock_fetch(
        lambda body: {
            "model": "jev-latest",
            "answers": {
                "choice": {
                    "type": "choice",
                    "choice": "billing",
                    "confidence": 0.8,
                    "probabilities": {"billing": 0.8, "orders": 0.1, "extra": 0.1},
                    "extra": "allowed",
                },
                "score": {
                    "type": "score",
                    "score": 1.5,
                    "confidence": 0.6,
                    "legend": {"0": "Calm", "1": "Civil", "2": "Angry", "extra": "allowed"},
                    "probabilities": {"0": 0.2, "1": 0.2, "2": 0.2, "extra": 0.4},
                },
            },
                    "usage": {"input_tokens": 2, "output_tokens": 1},
                }
    )
    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    questions = {
        "choice": {
            "type": "choice",
            "instructions": "where?",
            "criteria": {"billing": "Billing", "orders": "Orders"},
        },
        "score": {"type": "score", "instructions": "how?", "criteria": ["Calm", "Civil", "Angry"]},
    }
    first = cached(ENDPOINT, request(questions)).json()
    second = cached(ENDPOINT, request(questions)).json()
    assert first["answers"] == second["answers"]
    assert fetch.calls["n"] == 1


def test_error_responses_are_not_cached(tmp_path: Path) -> None:
    calls = {"n": 0}

    def fetch(_url: str, _init: dict | None = None) -> FetchResponse:
        calls["n"] += 1
        return FetchResponse(
            status=429,
            body=b"rate limited",
            headers={"retry-after": "1", "x-typesafe-request-id": "req_1"},
        )

    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    init = request({"a": {"type": "noul", "instructions": "A?"}})
    response = cached(ENDPOINT, init)
    assert response.status == 429
    assert response.text() == "rate limited"
    cached(ENDPOINT, init)
    assert calls["n"] == 2


def test_non_system_one_traffic_is_forwarded(tmp_path: Path) -> None:
    def fetch(url: str, _init: dict | None = None) -> FetchResponse:
        return FetchResponse(status=200, body=json.dumps({"url": url}).encode("utf-8"))

    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    response = cached("https://api.typesafe.ai/v1/models")
    assert "/v1/models" in response.json()["url"]


def test_cache_stats_skips_malformed_files(tmp_path: Path) -> None:
    digest = "a" * 64
    shard = tmp_path / digest[:2]
    shard.mkdir()
    (shard / f"{digest}.json").write_text(
        json.dumps(
            {
                "hash": digest,
                "requestedModel": "jev-latest",
                "reportedModel": "__proto__",
                "answer": {"type": "noul", "noul": 0.9},
            }
        ),
        encoding="utf-8",
    )
    (shard / "broken.json").write_text("not-json", encoding="utf-8")
    (shard / "array.json").write_text("[]", encoding="utf-8")
    stats = cache_stats(str(tmp_path))
    assert stats["entries"] == 1
    assert stats["models"]["__proto__"] == 1


def test_clear_cache_refuses_unexpected_directories(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="refusing to clear"):
        clear_cache(str(tmp_path / "not-cache"))
    allowed = tmp_path / ".systemoneprompts" / "cache"
    allowed.mkdir(parents=True)
    (allowed / "keep.txt").write_text("x", encoding="utf-8")
    clear_cache(str(allowed))
    assert not allowed.exists()


def test_null_state_is_not_the_omitted_state_hash() -> None:
    question = {"type": "noul", "instructions": "A?"}
    assert question_hash({"model": "jev-latest", "state": None, "question": question}) != question_hash(
        {"model": "jev-latest", "question": question}
    )
    assert question_hash({"model": None, "state": None, "question": question}) == question_hash(
        {"state": None, "question": question}
    )
    question = {"type": "noul", "instructions": "A?"}
    state = {"ticket": "hi"}
    assert question_hash({"model": "jev-latest", "state": state, "question": question}) != question_hash(
        {"state": state, "question": question}
    )


def test_default_fetch_forwards_cache_misses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_fetch(url: str, init: dict | None = None) -> FetchResponse:
        seen["url"] = url
        seen["body"] = (init or {}).get("body")
        return FetchResponse(
            status=200,
            body=json.dumps(
                {
                    "model": "jev-latest",
                    "answers": {"a": {"type": "noul", "noul": 0.5}},
                    "usage": {"input_tokens": 4, "output_tokens": 1},
                }
            ).encode("utf-8"),
        )

    monkeypatch.setattr("systemoneprompts.cache._stdlib_fetch", fake_fetch)
    cached = create_caching_fetch(dir=str(tmp_path))
    payload = cached(ENDPOINT, request({"a": {"type": "noul", "instructions": "A?"}})).json()
    assert seen["url"] == ENDPOINT
    assert payload["answers"]["a"]["noul"] == 0.5
    replay = cached(ENDPOINT, request({"a": {"type": "noul", "instructions": "A?"}})).json()
    assert replay["usage"]["input_tokens"] == 0


def test_absent_state_key_hashes_differently_from_null_state(tmp_path: Path) -> None:
    question = {"type": "noul", "instructions": "A?"}
    fetch = mock_fetch(lambda body: {"answers": {"q": {"type": "noul", "noul": 0.5}}})
    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    cached(ENDPOINT, {"method": "POST", "body": json.dumps({"model": "m", "questions": {"q": question}})})
    cached(ENDPOINT, {"method": "POST", "body": json.dumps({"model": "m", "state": None, "questions": {"q": question}})})
    assert fetch.calls["n"] == 2  # type: ignore[attr-defined]
    written = {path.stem for path in tmp_path.rglob("*.json")}
    assert written == {
        question_hash({"model": "m", "question": question}),
        question_hash({"model": "m", "state": None, "question": question}),
    }


def test_records_are_written_like_typescript(tmp_path: Path) -> None:
    question = {"type": "noul", "instructions": "é \ud800"}
    fetch = mock_fetch(lambda body: {"model": "m-2", "answers": {"q": {"type": "noul", "noul": 1.0}}})
    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    cached(ENDPOINT, {"method": "POST", "body": json.dumps({"model": "m", "state": None, "questions": {"q": question}})})
    digest = question_hash({"model": "m", "state": None, "question": question})
    text = (tmp_path / digest[:2] / f"{digest}.json").read_text(encoding="utf-8")
    assert text == (
        "{\n"
        f'  "hash": "{digest}",\n'
        '  "requestedModel": "m",\n'
        '  "reportedModel": "m-2",\n'
        '  "answer": {\n'
        '    "type": "noul",\n'
        '    "noul": 1\n'
        "  }\n"
        "}\n"
    )


def test_hostile_bodies_and_records_are_handled_like_javascript(tmp_path: Path) -> None:
    seen: list[str] = []

    def fetch(_url: str, init: dict | None = None) -> FetchResponse:
        body = str((init or {}).get("body"))
        body.encode("utf-8")  # a forwarded body must be transmittable
        seen.append(body)
        return FetchResponse(
            status=200,
            body=json.dumps({"answers": {"q": {"type": "noul", "noul": 0.5}}}).encode("utf-8"),
        )

    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    huge = "1" + "0" * 400
    for body in (
        '{"model":"m","state":' + huge + ',"questions":{"q":{"type":"noul"}}}',
        '{"model":"m","state":null,"questions":{"q":{"type":"noul","x":' + "1" * 5000 + "}}}",
        '{"model":"m","state":{"²":1},"questions":{"q":{"type":"noul"}}}',
        '{"model":"m","state":null,"questions":{"q":{"type":"noul","instructions":"\\ud800"}}}',
    ):
        assert cached(ENDPOINT, {"method": "POST", "body": body}).status == 200
    assert '"state":null' in seen[0]  # Infinity -> null, like JSON.stringify
    assert '"instructions":"\\ud800"' in seen[3]

    # Corrupt or over-precise records are misses, never tracebacks.
    records = tmp_path / "records"
    cached = create_caching_fetch(dir=str(records), fetch=fetch)
    digest = question_hash({"model": "m", "state": None, "question": {"type": "noul"}})
    path = records / digest[:2] / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = '{"model":"m","state":null,"questions":{"q":{"type":"noul"}}}'
    for content in (
        b'{"hash":"%s","reportedModel":"x","answer":{"type":"noul","noul":0.5},"extra":NaN}',
        b'{"hash":"%s","reportedModel":"x","answer":{"type":"noul","noul":' + huge.encode() + b"}}",
        b'{"hash":"%s","reportedModel":"x","answer":{"type":"noul","noul":0.5,"x":'
        + b"[" * 100_000
        + b"]" * 100_000
        + b"}}",
        b"\xff\xfe not json",
    ):
        path.write_bytes(content.replace(b"%s", digest.encode()))
        assert cache_stats(str(records))["entries"] == 0
        before = len(seen)
        assert cached(ENDPOINT, {"method": "POST", "body": body}).status == 200
        assert len(seen) == before + 1  # re-fetched
    # Undecodable bytes inside a string become U+FFFD and the record still counts.
    path.write_bytes(
        b'{"hash":"%s","reportedModel":"x\xff","answer":{"type":"noul","noul":0.5}}'.replace(b"%s", digest.encode())
    )
    assert cache_stats(str(records))["models"] == {"x\ufffd": 1}


def test_nonstandard_json_bodies_are_forwarded(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fetch(_url: str, init: dict | None = None) -> FetchResponse:
        seen["body"] = (init or {}).get("body")
        return FetchResponse(status=200, body=b"forwarded")

    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    init = {
        "method": "POST",
        "body": '{"model":"jev-latest","state":NaN,"questions":{"a":{"type":"noul"}}}',
    }
    response = cached(ENDPOINT, init)
    assert seen["body"] == init["body"]
    assert response.text() == "forwarded"
