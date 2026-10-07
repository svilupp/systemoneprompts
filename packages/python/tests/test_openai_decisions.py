from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx2
import pytest

from provider_fixtures import provider_fixtures
from systemoneprompts import (
    OpenAIDecisionsClient,
    OpenAIDecisionsError,
    check_definition,
    parse_definition,
    run_many,
)
from systemoneprompts.client import TypeSafeClient
from systemoneprompts.provider import LiveClientError, create_client

CORPUS = Path(__file__).resolve().parents[1] / "conformance/v1/providers"
FIXTURES = provider_fixtures("openai-decisions")


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f["name"])
def test_shared_adapter(fixture):
    calls = []

    def handle(request):
        calls.append(request)
        assert str(request.url) == "https://api.openai.com/v1/decisions"
        assert request.headers["authorization"] == "Bearer openai-test"
        assert json.loads(request.content) == fixture["request"]
        return httpx2.Response(200, json=fixture["response"], headers={"x-request-id": "req-test"})

    client = OpenAIDecisionsClient(api_key="openai-test", transport=httpx2.MockTransport(handle))
    try:
        if "error" in fixture:
            with pytest.raises(OpenAIDecisionsError) as caught:
                asyncio.run(
                    client.system_one(state=fixture["state"], questions=fixture["questions"])
                )
            assert caught.value.kind == fixture["error"]
            assert caught.value.body == fixture["response"]
            assert caught.value.request_id == "req-test"
            if fixture["error"] == "refusal":
                assert caught.value.refused_ids == ["charged.twice"]
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


@pytest.mark.parametrize(
    "state,encoded",
    [
        ("text", "text"),
        (None, "null"),
        (True, "true"),
        ([1, None], "[1,null]"),
        ({"z": 1e-7, "a": "é"}, '{"a":"é","z":1e-7}'),
        (9007199254740993, "9007199254740992"),
    ],
)
def test_evidence_encoding(state, encoded):
    def handle(request):
        assert json.loads(request.content)["input"] == encoded
        return httpx2.Response(
            200,
            json={
                "model": "test",
                "answers": [{"type": "predicate", "name": "q0", "probability": 0.9}],
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        )

    client = OpenAIDecisionsClient(transport=httpx2.MockTransport(handle))
    try:
        asyncio.run(
            client.system_one(state=state, questions={"n": {"type": "noul", "instructions": "OK?"}})
        )
    finally:
        client.close()


def test_preflight_zero_requests():
    calls = []
    client = OpenAIDecisionsClient(transport=httpx2.MockTransport(lambda r: calls.append(r)))
    questions = {"n": {"type": "noul", "instructions": "OK?"}}
    cyclic = []
    cyclic.append(cyclic)
    try:
        for state in [float("nan"), object(), cyclic]:
            with pytest.raises(OpenAIDecisionsError):
                asyncio.run(client.system_one(state=state, questions=questions))
        for invalid in [
            {},
            {"n": {"type": "noul"}},
            {"c": {"type": "choice", "criteria": {"only": None}}},
        ]:
            with pytest.raises(OpenAIDecisionsError):
                asyncio.run(client.system_one(state={}, questions=invalid))
        with pytest.raises(OpenAIDecisionsError, match="nonblank"):
            asyncio.run(client.system_one(state={}, questions=questions, model=" "))
        with pytest.raises(OpenAIDecisionsError):
            OpenAIDecisionsClient(model="", transport=httpx2.MockTransport(lambda r: None))
        assert not calls
    finally:
        client.close()


@pytest.mark.parametrize("fixture", json.loads((CORPUS / "provider-selection.json").read_text()))
def test_provider_parse(fixture):
    definition = parse_definition(fixture["source"])
    errors = [d for d in check_definition(definition) if d.code == "provider-value"]
    assert bool(errors) == (not fixture["valid"])
    assert definition.provider == fixture["provider"]
    if fixture["valid"]:
        assert definition.meta["provider"] == fixture["provider"]
    else:
        assert errors[0].line == 1


def test_selection_and_models():
    definition = parse_definition(
        'provider="openai"\n[questions.n]\ntype="noul"\ninstructions="OK?"'
    )
    transport = httpx2.MockTransport(lambda r: None)
    env = {"OPENAI_API_KEY": "openai", "TYPESAFE_API_KEY": "typesafe", "TYPESAFE_MODEL": "wrong"}
    created = create_client(definition, env=env, transport=transport)
    assert isinstance(created["client"], OpenAIDecisionsClient)
    assert created["model"] == "gpt-6-luna"
    created["client"].close()
    definition.model = "jev-latest"
    for override, model in [(None, "jev-latest"), ("custom", "custom")]:
        created = create_client(definition, env=env, transport=transport, model=override)
        assert created["model"] == model
        created["client"].close()
    created = create_client(definition, env=env, transport=transport, provider="typesafe")
    assert isinstance(created["client"], TypeSafeClient)
    created["client"].close()
    for kwargs, code in [
        ({"model": " "}, "openai-model-empty"),
        ({"provider": "unknown"}, "provider-value"),
    ]:
        with pytest.raises(LiveClientError) as caught:
            create_client(definition, env=env, **kwargs)
        assert caught.value.diagnostic.code == code


def test_http_retry_and_owned_headers():
    calls = []
    fixture = FIXTURES[0]

    def handle(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer test"
        return (
            httpx2.Response(429, json={"error": "retry"}, headers={"retry-after": "0"})
            if len(calls) == 1
            else httpx2.Response(200, json=fixture["response"])
        )

    client = OpenAIDecisionsClient(
        api_key="test", transport=httpx2.MockTransport(handle), headers={"authorization": "wrong"}
    )
    try:
        asyncio.run(
            client.system_one(
                state=fixture["state"],
                questions=fixture["questions"],
                headers={"AUTHORIZATION": "wrong"},
            )
        )
        assert len(calls) == 2
    finally:
        client.close()

    def bad(request):
        calls.append(request)
        return httpx2.Response(
            400, json={"error": "bad"}, headers={"x-request-id": "req-bad", "retry-after": "100"}
        )

    client = OpenAIDecisionsClient(transport=httpx2.MockTransport(bad))
    try:
        with pytest.raises(OpenAIDecisionsError) as caught:
            asyncio.run(client.system_one(state=fixture["state"], questions=fixture["questions"]))
        assert (
            caught.value.kind,
            caught.value.status,
            caught.value.request_id,
            caught.value.retry_after,
        ) == ("http", 400, "req-bad", 60)
        assert len(calls) == 3
    finally:
        client.close()


def test_injected_http_ownership_and_patterns():
    questions = {"n": {"type": "noul", "instructions": "OK?"}}
    for cls, path in [(TypeSafeClient, "/v1/systemone"), (OpenAIDecisionsClient, "/v1/decisions")]:

        def handle(request, path=path, cls=cls):
            assert request.url.path == path
            answers = (
                {"n": {"type": "noul", "noul": 0.9}}
                if cls is TypeSafeClient
                else [{"name": "q0", "type": "predicate", "probability": 0.9}]
            )
            return httpx2.Response(
                200,
                json={
                    "model": "test",
                    "answers": answers,
                    "usage": {"input_tokens": 1, "output_tokens": 0},
                },
            )

        http = httpx2.Client(transport=httpx2.MockTransport(handle))
        client = cls(http_client=http)
        try:
            assert (
                asyncio.run(client.system_one(state="OK", questions=questions))["answers"]["n"][
                    "noul"
                ]
                == 0.9
            )
            assert len(asyncio.run(run_many(client, questions=questions, states=["OK"]))) == 1
            client.close()
            assert not http.is_closed
        finally:
            http.close()


def test_async_cancellation_timeout_and_transport_ownership():
    calls = []

    class InjectedHTTP:
        async def request(self, *args, **kwargs):
            calls.append(args)
            raise httpx2.ReadTimeout("test timeout")

    client = OpenAIDecisionsClient(http_client=InjectedHTTP(), max_retries=0)
    with pytest.raises(OpenAIDecisionsError) as caught:
        asyncio.run(
            client.system_one(state="OK", questions={"n": {"type": "noul", "instructions": "OK?"}})
        )
    assert caught.value.kind == "timeout"
    assert len(calls) == 1

    class WaitingHTTP:
        async def request(self, *args, **kwargs):
            calls.append(args)
            await asyncio.sleep(60)

    async def cancel():
        client = OpenAIDecisionsClient(http_client=WaitingHTTP())
        task = asyncio.create_task(
            client.system_one(state="OK", questions={"n": {"type": "noul", "instructions": "OK?"}})
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    assert len(calls) == 2

    class Borrowed(httpx2.BaseTransport):
        closed = False

        def handle_request(self, request):
            return httpx2.Response(200, json=FIXTURES[0]["response"])

        def close(self):
            self.closed = True

    transport = Borrowed()
    OpenAIDecisionsClient(transport=transport).close()
    assert not transport.closed


def test_cli_openai_preflight_and_offline_generation(tmp_path, monkeypatch, capsys):
    from systemoneprompts.cli import main

    source = 'provider="openai"\n[requires]\nx="string"\n[questions.n]\ntype="noul"\ninstructions="Is `x` OK?"'
    definition = tmp_path / "test.toml"
    definition.write_text(source)
    state = tmp_path / "state.json"
    state.write_text('{"x":"OK"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert main(["check", str(definition)]) == 0
    assert main(["generate", str(definition)]) == 0
    import runpy
    assert runpy.run_path(str(tmp_path / "test_generated.py"))["meta"]["provider"] == "openai"
    calls = []

    class NoNetwork:
        def request(self, *args, **kwargs):
            calls.append(args)
            raise AssertionError("unexpected network")

        def close(self):
            pass

    monkeypatch.setattr(httpx2, "Client", lambda **kwargs: NoNetwork())
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    for extra in [["--model", " "], ["--provider", "unknown"]]:
        assert main(["run", str(definition), "--state", str(state), *extra]) == 1
    state.write_text("{}")
    assert main(["run", str(definition), "--state", str(state)]) == 1
    state.write_text('{"x":"OK"}')
    definition.write_text('provider="openai"\n[questions.c]\ntype="choice"\ncriteria={only="Only"}')
    assert main(["run", str(definition), "--state", str(state)]) == 1
    assert not calls
    assert "needs at least two options" in capsys.readouterr().err


def test_taxonomy_accepts_either_rest_client():
    from systemoneprompts import walk_taxonomy

    for cls in [TypeSafeClient, OpenAIDecisionsClient]:

        def handle(request, cls=cls):
            answers = (
                {
                    "step": {
                        "type": "choice",
                        "choice": "A",
                        "confidence": 0.8,
                        "probabilities": {"A": 0.8, "B": 0.2},
                    }
                }
                if cls is TypeSafeClient
                else [
                    {
                        "name": "q0",
                        "type": "choice",
                        "choice": "A",
                        "confidence": 0.8,
                        "probabilities": [
                            {"value": "A", "probability": 0.8},
                            {"value": "B", "probability": 0.2},
                        ],
                    }
                ]
            )
            return httpx2.Response(
                200,
                json={
                    "model": "test",
                    "answers": answers,
                    "usage": {"input_tokens": 1, "output_tokens": 0},
                },
            )

        client = cls(transport=httpx2.MockTransport(handle))
        try:
            paths = asyncio.run(
                walk_taxonomy(client, state="evidence", tree={"A": "First", "B": "Second"})
            )
            assert paths[0]["path"] == ["A"]
            assert paths[0]["probability"] == 0.8
        finally:
            client.close()
