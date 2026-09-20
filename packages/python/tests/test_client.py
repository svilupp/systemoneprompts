from __future__ import annotations

import asyncio
import json
import time
from email.utils import formatdate
from types import SimpleNamespace

import pytest

from systemoneprompts.client import (
    TypeSafeClient,
    TypeSafeClientError,
    TypeSafeHttpError,
    TypeSafeRateLimitError,
)

httpx2 = pytest.importorskip("httpx2")


def _ok_body(noul: float = 0.7) -> dict[str, object]:
    return {
        "model": "jev-test",
        "answers": {"q": {"type": "noul", "noul": noul}},
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def test_typesafe_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(TypeSafeClientError) as caught:
        TypeSafeClient()
    assert caught.value.diagnostic.code == "missing-credentials"


def test_typesafe_client_posts_json_with_bearer_auth() -> None:
    seen: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_ok_body())

    client = TypeSafeClient(
        api_key="test-key",
        base_url="https://api.example.test",
        model="jev-test",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    result = asyncio.run(
        client.system_one(state={"text": "now"}, questions={"q": {"type": "noul"}})
    )
    client.close()
    assert result["answers"]["q"]["noul"] == 0.7
    request = seen[0]
    request.read()
    assert request.method == "POST"
    assert str(request.url) == "https://api.example.test/v1/systemone"
    assert request.headers.get("authorization") == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "jev-test"
    assert body["state"] == {"text": "now"}


def test_typesafe_client_does_not_retry_400() -> None:
    calls = {"n": 0}

    def respond(_request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        return httpx2.Response(400, text="nope")

    client = TypeSafeClient(
        api_key="test",
        transport=httpx2.MockTransport(respond),
        max_retries=2,
    )
    with pytest.raises(TypeSafeHttpError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert caught.value.status == 400
    assert calls["n"] == 1


def test_typesafe_client_retries_503_then_succeeds() -> None:
    calls = {"n": 0}

    def respond(_request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(503, text="busy")
        return httpx2.Response(200, json=_ok_body(0.9))

    client = TypeSafeClient(
        api_key="test",
        transport=httpx2.MockTransport(respond),
        max_retries=2,
    )
    result = asyncio.run(client.system_one(state=None, questions={"q": {"type": "noul"}}))
    client.close()
    assert result["answers"]["q"]["noul"] == 0.9
    assert calls["n"] == 2


def test_injected_http_client_keeps_its_timeout_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    captured: dict[str, object] = {}

    class CallerClient:
        def request(self, method: str, url: str, **kwargs: object) -> SimpleNamespace:
            captured["method"] = method
            captured["url"] = url
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                status_code=200,
                headers={},
                text="",
                json=lambda: _ok_body(),
            )

    client = TypeSafeClient(http_client=CallerClient(), timeout=99)
    result = asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    assert result["answers"]["q"]["noul"] == 0.7
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert "timeout" not in kwargs
    headers = kwargs["headers"]
    assert isinstance(headers, dict)
    assert "Authorization" not in headers
    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"


def test_injected_http_client_uses_call_timeout_and_api_key() -> None:
    captured: dict[str, object] = {}

    class CallerClient:
        def request(self, method: str, url: str, **kwargs: object) -> SimpleNamespace:
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                status_code=200,
                headers={},
                text="",
                json=lambda: _ok_body(),
            )

    client = TypeSafeClient(api_key="from-jev", http_client=CallerClient())
    asyncio.run(
        client.system_one(
            state={},
            questions={"q": {"type": "noul"}},
            timeout=3.5,
            headers={"Authorization": "Bearer other"},
        )
    )
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["timeout"] == 3.5
    headers = kwargs["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer from-jev"


def test_programming_errors_are_not_retried() -> None:
    calls = {"n": 0}

    class Boom:
        def request(self, method: str, url: str, **kwargs: object) -> SimpleNamespace:
            calls["n"] += 1
            raise TypeError("caller client does not accept json=")

    client = TypeSafeClient(api_key="test", http_client=Boom(), max_retries=2)
    with pytest.raises(TypeSafeClientError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    assert calls["n"] == 1
    assert caught.value.diagnostic.code == "provider-client"


def test_choice_answer_requires_probabilities() -> None:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "model": "jev-test",
                "answers": {
                    "q": {"type": "choice", "choice": "billing", "confidence": 0.8},
                },
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = TypeSafeClient(
        api_key="test",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    with pytest.raises(TypeSafeClientError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "choice"}}))
    client.close()
    assert caught.value.diagnostic.code == "provider-response"


def test_invalid_system_one_body_is_a_provider_response_error() -> None:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"model": "jev-test", "answers": {"q": {"type": "noul"}}})

    client = TypeSafeClient(
        api_key="test",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    with pytest.raises(TypeSafeClientError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert caught.value.diagnostic.code == "provider-response"


def test_429_is_rate_limit_error() -> None:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, text="slow down", headers={"Retry-After": "1"})

    client = TypeSafeClient(
        api_key="test",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    with pytest.raises(TypeSafeRateLimitError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert isinstance(caught.value, TypeSafeHttpError)
    assert caught.value.retry_after == 1.0


def test_http_date_retry_after() -> None:
    when = formatdate(timeval=time.time() + 2, usegmt=True)

    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, text="later", headers={"Retry-After": when})

    client = TypeSafeClient(
        api_key="test",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    with pytest.raises(TypeSafeRateLimitError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert caught.value.retry_after is not None
    assert abs(caught.value.retry_after - 2.0) <= 1.0


def test_system_one_sync_posts_json() -> None:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=_ok_body())

    client = TypeSafeClient(
        api_key="test-key",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    result = client.system_one_sync(state={}, questions={"q": {"type": "noul"}})
    client.close()
    assert result["answers"]["q"]["noul"] == 0.7


def test_system_one_sync_rejects_async_http_client() -> None:
    class AsyncCaller:
        async def request(self, method: str, url: str, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(status_code=200, headers={}, text="", json=lambda: _ok_body())

    client = TypeSafeClient(api_key="test", http_client=AsyncCaller())
    with pytest.raises(TypeSafeClientError) as caught:
        client.system_one_sync(state={}, questions={"q": {"type": "noul"}})
    assert "system_one_sync" in str(caught.value)


def test_empty_questions_rejected() -> None:
    client = TypeSafeClient(
        api_key="test", transport=httpx2.MockTransport(lambda r: httpx2.Response(200))
    )
    with pytest.raises(TypeSafeClientError) as caught:
        asyncio.run(client.system_one(state={}, questions={}))
    client.close()
    assert caught.value.diagnostic.code == "provider-client"
