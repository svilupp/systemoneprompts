from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx2
import pytest

from systemoneprompts.client import TypeSafeClient, TypeSafeClientError
from systemoneprompts.definition import parse_definition
from systemoneprompts.openai_decisions import OpenAIDecisionsClient
from systemoneprompts.openrouter import openrouter_base_url, openrouter_cache_dir
from systemoneprompts.provider import create_client

FIXTURE = json.loads((Path(__file__).parents[1] / "conformance/v1/providers/native-decisions.json").read_text())


@pytest.mark.parametrize("model", FIXTURE["models"])
def test_native_wire(model: str) -> None:
    seen = []
    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        assert str(request.url) == "https://openrouter.ai/api/alpha/decisions"
        assert request.headers["Authorization"] == "Bearer router-key"
        assert json.loads(request.content) == {"state": FIXTURE["state"], "questions": FIXTURE["questions"], "model": model}
        return httpx2.Response(200, json=FIXTURE["response"])
    client = TypeSafeClient(provider="openrouter", model=model, environ={"OPENROUTER_API_KEY": "router-key", "TYPESAFE_API_KEY": "ignored", "TYPESAFE_BASE_URL": "https://ignored.test", "CLOUDFLARE_ACCOUNT_ID": "ignored"}, transport=httpx2.MockTransport(respond))
    try:
        result = asyncio.run(client.system_one(state=FIXTURE["state"], questions=FIXTURE["questions"]))
        assert result == FIXTURE["response"]
        assert len(seen) == 1
    finally:
        client.close()


def test_selection_and_cache(tmp_path: Path) -> None:
    definition = parse_definition('provider = "openrouter"\nbase_url = "https://toml.test/alpha"\nmodel = "openai/gpt-6-luna-decisions"\n[questions.q]\ntype = "noul"\ninstructions = "OK?"')
    assert definition.base_url == "https://toml.test/alpha"
    calls = []
    def respond(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        assert str(request.url) == "https://cli.test/alpha/decisions"
        return httpx2.Response(200, json=FIXTURE["response"])
    created = create_client(definition, base_url="https://cli.test/alpha", cache=True, cache_root=str(tmp_path), env={"OPENROUTER_API_KEY": "router-key"}, transport=httpx2.MockTransport(respond))
    try:
        for _ in range(2):
            result = asyncio.run(created["client"].system_one(state=FIXTURE["state"], questions=FIXTURE["questions"]))
        assert len(calls) == 1
        assert result["usage"]["input_tokens"] == 0
        assert result["answers"]["frustration"]["score"] == 1.5
        assert created["model"] == "openai/gpt-6-luna-decisions"
    finally:
        created["raw"].close()
    assert openrouter_cache_dir(dir=str(tmp_path)) == openrouter_cache_dir(dir=str(tmp_path), base_url="https://openrouter.ai/api/alpha/decisions/")
    assert openrouter_cache_dir(dir=str(tmp_path)) != openrouter_cache_dir(dir=str(tmp_path), base_url="https://other.test/alpha")


@pytest.mark.parametrize("value", ["", "ftp://host", "https://key@host", "https://host?secret=key", "https://host#part"])
def test_invalid_urls(value: str) -> None:
    with pytest.raises(Exception, match="base_url"):
        openrouter_base_url(value)
    parsed = parse_definition(f'base_url = {json.dumps(value)}\n[questions.q]\ntype = "noul"')
    assert any(d.code == "base-url" and d.line == 1 for d in parsed.diagnostics)


def test_key_and_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(TypeSafeClientError, match="OPENROUTER_API_KEY"):
        TypeSafeClient(provider="openrouter", environ={"TYPESAFE_API_KEY": "native-key"})
    monkeypatch.setenv("OPENAI_BASE_URL", "https://direct.test/v1/decisions")
    client = OpenAIDecisionsClient(api_key="openai-key")
    try:
        assert client.base_url == "https://direct.test/v1"
    finally:
        client.close()


@pytest.mark.parametrize("fixture", json.loads((Path(__file__).parents[1] / "conformance/v1/providers/endpoint-selection.json").read_text()))
def test_shared_endpoint_diagnostics(fixture: dict[str, object]) -> None:
    definition = parse_definition(str(fixture["source"]))
    assert any(d.code == "base-url" and d.line == 1 for d in definition.diagnostics)
