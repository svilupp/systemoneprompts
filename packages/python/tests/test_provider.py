from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from helpers import fixture, fixture_path
from systemoneprompts import parse_definition
from systemoneprompts.provider import (
    FakeClient,
    LiveClientError,
    create_client,
    load_dotenv,
    native_result,
)


def test_native_result_from_mapping_and_object() -> None:
    dumped = native_result(
        {
            "model": "jev-test",
            "answers": {"urgent": {"type": "noul", "noul": 0.8}},
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }
    )
    assert dumped["answers"]["urgent"]["noul"] == 0.8
    assert dumped["usage"]["input_tokens"] == 1

    class Answer:
        def model_dump(self, mode: str = "json") -> dict[str, object]:
            return {"type": "noul", "noul": 0.4}

    class Usage:
        input_tokens = 3
        output_tokens = 4

    class Response:
        model = "sdk"
        answers = {"q": Answer()}
        usage = Usage()

    assert native_result(Response())["answers"]["q"] == {"type": "noul", "noul": 0.4}


def test_fake_client_records_calls() -> None:
    import asyncio

    client = FakeClient(lambda request: {"model": request["model"], "answers": {}, "usage": {}})
    result = asyncio.run(client.system_one(state={"a": 1}, questions={"q": {"type": "noul"}}, model="x"))
    assert result["model"] == "x"
    assert client.calls[0]["state"] == {"a": 1}


def test_load_dotenv_does_not_override_existing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=from-file\nOTHER=value\n", encoding="utf-8")
    monkeypatch.setenv("TYPESAFE_API_KEY", "already")
    monkeypatch.delenv("OTHER", raising=False)
    load_dotenv(str(tmp_path))
    assert os.environ["TYPESAFE_API_KEY"] == "already"
    assert os.environ["OTHER"] == "value"


def test_create_client_missing_live_or_credentials(monkeypatch) -> None:
    definition = parse_definition(fixture("golden/noul-string.toml"))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(LiveClientError) as caught:
        create_client(definition, env={})
    assert caught.value.diagnostic.code in {"missing-live", "missing-credentials"}


def test_typesafe_client_uses_caller_transport() -> None:
    httpx2 = pytest.importorskip("httpx2")
    from systemoneprompts.client import TypeSafeClient

    def respond(request):  # type: ignore[no-untyped-def]
        return httpx2.Response(
            200,
            json={
                "model": "jev-test",
                "answers": {"q": {"type": "noul", "noul": 0.7}},
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = TypeSafeClient(
        api_key="test",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    result = asyncio.run(
        client.system_one(state={"a": 1}, questions={"q": {"type": "noul"}}, model="x")
    )
    assert result["model"] == "jev-test"
    assert result["answers"]["q"]["noul"] == 0.7
    client.close()


def test_wrap_caching_fetch_maps_httpx_requests(tmp_path, monkeypatch) -> None:
    import json
    import sys
    import types

    from systemoneprompts.cache import FetchResponse, create_caching_fetch
    from systemoneprompts.provider import wrap_caching_fetch

    class Request:
        def __init__(self, method: str = "GET", url: str = "", headers=None, content: bytes = b""):
            self.method = method
            self.url = url
            self.headers = headers or {}
            self.content = content

        def read(self) -> None:
            return None

    class Response:
        def __init__(self, status: int, headers=None, content: bytes = b"", request=None):
            self.status_code = status
            self.headers = headers or []
            self.content = content
            self.request = request

    dummy = types.SimpleNamespace(
        Request=Request,
        Response=Response,
        BaseTransport=object,
        HTTPTransport=object,
    )
    monkeypatch.setitem(sys.modules, "httpx2", dummy)

    calls = {"n": 0}

    def fetch(_url: str, _init: dict | None = None) -> FetchResponse:
        calls["n"] += 1
        return FetchResponse(
            status=200,
            body=json.dumps(
                {
                    "model": "jev-test",
                    "answers": {"a": {"type": "noul", "noul": 0.9}},
                    "usage": {"input_tokens": 2, "output_tokens": 1},
                }
            ).encode("utf-8"),
            headers={"content-type": "application/json"},
        )

    cached = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    transport = wrap_caching_fetch(cached)
    body = json.dumps(
        {
            "model": "jev-latest",
            "state": {"ticket": "hi"},
            "questions": {"a": {"type": "noul", "instructions": "A?"}},
        }
    ).encode("utf-8")
    first = transport.handle_request(
        Request("POST", "https://api.typesafe.ai/v1/systemone", {"content-type": "application/json"}, body)
    )
    second = transport.handle_request(
        Request("POST", "https://api.typesafe.ai/v1/systemone", {"content-type": "application/json"}, body)
    )
    assert first.status_code == 200
    assert json.loads(second.content)["answers"]["a"]["noul"] == 0.9
    assert calls["n"] == 1


def test_cache_misses_forward_with_a_fresh_content_length(tmp_path: Path) -> None:
    """Regression: the rewritten miss body must not carry a stale Content-Length."""
    httpx2 = pytest.importorskip("httpx2")
    from systemoneprompts import load_definition
    from systemoneprompts.provider import create_client

    seen: list[dict[str, object]] = []

    def respond(request):  # type: ignore[no-untyped-def]
        payload = json.loads(request.content.decode("utf-8"))
        seen.append(
            {
                "declared": request.headers.get("content-length"),
                "actual": len(request.content),
                "questions": sorted(payload["questions"]),
            }
        )
        answers = {}
        for qid, question in payload["questions"].items():
            if question["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": 0.9}
            elif question["type"] == "choice":
                answers[qid] = {
                    "type": "choice",
                    "choice": "billing",
                    "confidence": 0.8,
                    "probabilities": {"billing": 0.8, "orders": 0.1, "account": 0.1},
                }
            else:
                answers[qid] = {
                    "type": "score",
                    "score": 1.7,
                    "confidence": 0.7,
                    "legend": {"0": "Calm", "1": "Civil", "2": "Angry"},
                    "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
                }
        return httpx2.Response(
            200,
            json={"model": "jev-test", "answers": answers, "usage": {"input_tokens": 3, "output_tokens": 2}},
        )

    definition = load_definition(str(fixture_path("golden/triage.toml")))
    state = {
        "ticket": {"message": "héllo wörld", "sender": {"email": "a@b.c", "display_name": "A"}},
        "customer": {"open_orders": []},
        "policy": {"sensitive_credentials": []},
    }
    created = create_client(
        definition,
        cache=True,
        cache_dir=str(tmp_path),
        env={"TYPESAFE_API_KEY": "test"},
        transport=httpx2.MockTransport(respond),
    )
    ids = list(definition.questions)

    # Warm a single question so the second call is a partial miss with a shorter body.
    first = asyncio.run(
        created["client"].system_one(
            state=state, questions={ids[0]: definition.questions[ids[0]]}, model="jev-test"
        )
    )
    assert set(first["answers"]) == {ids[0]}
    full = asyncio.run(
        created["client"].system_one(state=state, questions=definition.questions, model="jev-test")
    )
    assert set(full["answers"]) == set(ids)
    again = asyncio.run(
        created["client"].system_one(state=state, questions=definition.questions, model="jev-test")
    )
    assert again["usage"] == {"input_tokens": 0, "output_tokens": 0}

    assert len(seen) == 2, seen
    for request in seen:
        assert request["declared"] is None or int(str(request["declared"])) == request["actual"]
    assert seen[1]["questions"] == sorted(ids[1:])
    stats = created["cache"].stats()
    assert (stats.requests, stats.hits, stats.misses) == (3, 1 + len(ids), len(ids))
