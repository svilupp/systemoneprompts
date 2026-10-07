from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import httpx2
import pytest

from provider_fixtures import provider_fixtures
from systemoneprompts import CloudflareDecisionsClient, CloudflareDecisionsError, parse_definition
from systemoneprompts.cache import CacheMissError, cache_stats, question_hash
from systemoneprompts.cli import _cache
from systemoneprompts.dev import cloudflare_cache_dir, create_cached_cloudflare_decisions_client
from systemoneprompts.provider import create_client

FIXTURES = provider_fixtures("cloudflare-decisions")
BASE = FIXTURES[0]


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f["name"])
def test_shared_contract(fixture):
    calls = []

    def handle(request):
        calls.append(request)
        assert (
            str(request.url)
            == f"https://api.cloudflare.com/client/v4/accounts/test-account/ai/run/@cf/cloudflare/{fixture['request']['model']}"
        )
        assert request.headers["authorization"] == "Bearer test-token"
        assert json.loads(request.content) == fixture["request"]
        return httpx2.Response(200, json=fixture["response"], headers={"cf-ray": "test-ray"})

    client = CloudflareDecisionsClient(
        api_key="test-token",
        account_id="test-account",
        model=fixture["model"],
        transport=httpx2.MockTransport(handle),
    )
    try:
        if "error" in fixture:
            with pytest.raises(CloudflareDecisionsError) as caught:
                asyncio.run(
                    client.system_one(state=fixture["state"], questions=fixture["questions"])
                )
            assert caught.value.kind == fixture["error"]
            assert caught.value.body == fixture["response"]
            assert caught.value.request_id == "test-ray"
        else:
            assert (
                asyncio.run(
                    client.system_one(state=fixture["state"], questions=fixture["questions"])
                )
                == fixture["result"]
            )
        assert len(calls) == 1
    finally:
        client.close()


def test_preflight():
    calls = []
    client = CloudflareDecisionsClient(
        account_id="test-account", transport=httpx2.MockTransport(lambda r: calls.append(r))
    )
    try:
        for request in [
            {"state": float("nan"), "questions": BASE["questions"]},
            {"state": {}, "questions": {}},
            {"state": {}, "questions": {str(i): {"type": "noul"} for i in range(65)}},
            {"state": {}, "questions": BASE["questions"], "model": "jev-latest"},
            {"state": {}, "questions": BASE["questions"], "model": " "},
        ]:
            with pytest.raises(CloudflareDecisionsError):
                asyncio.run(client.system_one(**request))
        assert not calls
    finally:
        client.close()


def test_errors_and_retries():
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx2.Response(
                429, json={"errors": [{"message": "busy"}]}, headers={"retry-after": "0"}
            )
        return httpx2.Response(200, json=BASE["response"])

    client = CloudflareDecisionsClient(
        account_id="test-account", transport=httpx2.MockTransport(handle), max_retries=1
    )
    try:
        asyncio.run(client.system_one(state=BASE["state"], questions=BASE["questions"]))
        assert len(calls) == 2
    finally:
        client.close()
    for status in (200, 401):
        calls = []

        def failing(request, calls=calls, status=status):
            calls.append(request)
            return httpx2.Response(
                status, json={"success": False, "errors": [{"message": "denied"}]}
            )

        client = CloudflareDecisionsClient(
            account_id="test-account", transport=httpx2.MockTransport(failing)
        )
        try:
            with pytest.raises(CloudflareDecisionsError) as caught:
                asyncio.run(client.system_one(state={}, questions=BASE["questions"]))
            assert caught.value.kind == "http"
            assert caught.value.status == (400 if status == 200 else status)
            assert len(calls) == 1
        finally:
            client.close()


def test_cache(tmp_path, capsys):
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        answers = {
            identifier: next(
                copy.deepcopy(a)
                for a in BASE["response"]["result"]["answers"].values()
                if a["type"] == q["type"]
            )
            for identifier, q in body["questions"].items()
        }
        return httpx2.Response(
            200,
            json={
                "success": True,
                "result": {
                    "model": body["model"],
                    "answers": answers,
                    "usage": {"input_tokens": 123, "output_tokens": 0},
                },
            },
        )

    network = CloudflareDecisionsClient(
        account_id="test-account", transport=httpx2.MockTransport(handle)
    )
    made = create_cached_cloudflare_decisions_client(client=network, dir=str(tmp_path))
    readonly = create_cached_cloudflare_decisions_client(
        client=network, dir=str(tmp_path), mode="read-only"
    )
    request = {"state": BASE["state"], "questions": BASE["questions"]}
    first_id = next(iter(request["questions"]))

    async def run():
        await made["client"].system_one(
            state=request["state"], questions={first_id: request["questions"][first_id]}
        )
        result = await made["client"].system_one(**request)
        assert list(calls[1]["questions"]) == ["q0", "q1"]
        hit = await made["client"].system_one(**request, model="@cf/cloudflare/clef")
        assert hit["answers"] == result["answers"]
        assert hit["usage"] == {"input_tokens": 0, "output_tokens": 0}
        assert len(calls) == 2
        await made["client"].system_one(**request, model="clef-flash")
        assert len(calls) == 3
        assert cache_stats(made["cache"].dir)["entries"] == 6
        hash_value = question_hash(
            {
                "model": "clef",
                "id": first_id,
                "state": request["state"],
                "question": request["questions"][first_id],
            }
        )
        path = Path(made["cache"].dir) / hash_value[:2] / (hash_value + ".json")
        record = json.loads(path.read_text())
        record["answer"]["noul"] = 2
        path.write_text(json.dumps(record))
        with pytest.raises(CacheMissError):
            await readonly["client"].system_one(**request)
        await made["client"].system_one(**request)
        assert len(calls[3]["questions"]) == 1

    try:
        asyncio.run(run())
        assert (
            cloudflare_cache_dir(dir=str(tmp_path), account_id="other-account") != made["cache"].dir
        )
        assert (
            cloudflare_cache_dir(dir=str(tmp_path), base_url=network.base_url + "/")
            == made["cache"].dir
        )
        assert (
            _cache(
                "stats", provider="cloudflare", cache_root=str(tmp_path), base_url=network.base_url
            )
            == 0
        )
        assert "entries  6" in capsys.readouterr().out
        assert (
            _cache(
                "clear", provider="cloudflare", cache_root=str(tmp_path), base_url=network.base_url
            )
            == 0
        )
        assert cache_stats(made["cache"].dir)["entries"] == 0
    finally:
        readonly["client"].close()
        made["client"].close()
        network.close()


def test_invalid_live_writes_nothing(tmp_path):
    fixture = next(f for f in FIXTURES if f["name"] == "invalid-score")
    network = CloudflareDecisionsClient(
        account_id="test-account",
        transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=fixture["response"])),
    )
    made = create_cached_cloudflare_decisions_client(client=network, dir=str(tmp_path))
    try:
        with pytest.raises(CloudflareDecisionsError):
            asyncio.run(made["client"].system_one(state=BASE["state"], questions=BASE["questions"]))
        assert cache_stats(made["cache"].dir)["entries"] == 0
    finally:
        made["client"].close()
        network.close()


def test_provider_selection():
    env = {
        "CLOUDFLARE_API_TOKEN": "test",
        "CLOUDFLARE_ACCOUNT_ID": "test-account",
        "TYPESAFE_BASE_URL": "https://other.invalid",
        "TYPESAFE_MODEL": "jev-latest",
    }
    definition = parse_definition(
        'provider="cloudflare"\nmodel="@cf/cloudflare/clef-flash"\n[questions.n]\ntype="noul"'
    )
    made = create_client(definition, env=env)
    try:
        assert made["model"] == "clef-flash"
        assert isinstance(made["client"], CloudflareDecisionsClient)
    finally:
        made["raw"].close()


@pytest.mark.parametrize(
    "fixture",
    json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "conformance/v1/providers/cloudflare-compatibility.json"
        ).read_text()
    ),
    ids=lambda f: f["name"],
)
def test_compatibility(fixture):
    calls = []
    client = CloudflareDecisionsClient(
        account_id="test-account", transport=httpx2.MockTransport(lambda r: calls.append(r))
    )
    try:
        with pytest.raises(CloudflareDecisionsError) as caught:
            asyncio.run(client.system_one(state={}, questions=fixture["questions"]))
        assert caught.value.kind == "compatibility"
        assert caught.value.code == fixture["code"]
        assert not calls
    finally:
        client.close()


def test_sixty_four_questions_and_resource_ownership():
    closed = []

    class Transport(httpx2.BaseTransport):
        def handle_request(self, request):
            body = json.loads(request.content)
            return httpx2.Response(
                200,
                json={
                    "model": body["model"],
                    "answers": {
                        identifier: {"type": "noul", "noul": 0.9}
                        for identifier in body["questions"]
                    },
                    "usage": {"input_tokens": 1, "output_tokens": 0},
                },
            )

        def close(self):
            closed.append(True)

    client = CloudflareDecisionsClient(account_id="test-account", transport=Transport())
    try:
        result = asyncio.run(
            client.system_one(
                state={},
                questions={
                    str(i): {"type": "noul", "instructions": "Is it true?"} for i in range(64)
                },
            )
        )
        assert len(result["answers"]) == 64
    finally:
        client.close()
    assert not closed


def test_timeout_terminal():
    def handle(request):
        raise TimeoutError("timed out")

    client = CloudflareDecisionsClient(
        account_id="test-account", transport=httpx2.MockTransport(handle), max_retries=0
    )
    try:
        with pytest.raises(CloudflareDecisionsError) as caught:
            asyncio.run(client.system_one(state=BASE["state"], questions=BASE["questions"]))
        assert caught.value.kind == "timeout"
    finally:
        client.close()


def test_cache_missing_account_is_a_cli_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    assert _cache("stats", provider="cloudflare") == 1
    assert "CLOUDFLARE_ACCOUNT_ID is required" in capsys.readouterr().err


def test_retries_preserve_original_state_and_rubric():
    state = {"message": "original"}
    criteria = [{"impact": "low"}, {"impact": "high"}]
    questions = {"severity": {"type": "score", "instructions": "Rate impact", "criteria": criteria}}
    calls = []

    def handle(request):
        calls.append(request.content)
        if len(calls) == 1:
            state["message"] = "changed"
            criteria[0]["impact"] = "changed"
            return httpx2.Response(429, json={}, headers={"retry-after": "0"})
        return httpx2.Response(
            200,
            json={
                "model": "clef",
                "usage": {"input_tokens": 1, "output_tokens": 0},
                "answers": {
                    "q0": {
                        "type": "score",
                        "score": 0.5,
                        "confidence": 0.2,
                        "probabilities": {"0": 0.5, "1": 0.5},
                        "legend": {"0": {"impact": "low"}, "1": {"impact": "high"}},
                    },
                },
            },
        )

    client = CloudflareDecisionsClient(
        account_id="test-account", transport=httpx2.MockTransport(handle), max_retries=1
    )
    try:
        result = asyncio.run(client.system_one(state=state, questions=questions))
        assert len(calls) == 2
        assert calls[0] == calls[1]
        assert result["answers"]["severity"]["legend"]["0"] == {"impact": "low"}
    finally:
        client.close()


@pytest.mark.parametrize("example", ["11-openai-decisions", "12-cloudflare-decisions"])
def test_provider_sample_eval_cases_pass_preflight(example):
    from systemoneprompts import load_definition
    from systemoneprompts.evaluation import load_eval_cases

    root = Path(__file__).resolve().parents[1] / "examples" / example
    cases = load_eval_cases(
        (root / "cases.jsonl").read_text(), "sample", load_definition(root / "ticket.toml")
    )
    assert len(cases) == 7
    assert [
        sum(label in case["labels"] for case in cases)
        for label in ("duplicate", "department", "severity")
    ] == [5, 6, 6]
