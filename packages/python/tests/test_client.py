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
from systemoneprompts.cloudflare import CLOUDFLARE_MODEL, cloudflare_run_url

httpx2 = pytest.importorskip("httpx2")


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "TYPESAFE_API_KEY",
        "TYPESAFE_BASE_URL",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


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


def test_oversized_retry_after_ms_falls_through_to_retry_after() -> None:
    from systemoneprompts.client import _retry_after_seconds

    assert _retry_after_seconds({"retry-after-ms": "250"}) == 0.25
    assert _retry_after_seconds({"retry-after-ms": "60001", "retry-after": "1"}) == 1.0
    assert _retry_after_seconds({"retry-after-ms": "-5", "retry-after": "120"}) == 60.0
    assert _retry_after_seconds({"retry-after": "soon"}) is None


def test_client_owned_headers_win_regardless_of_casing() -> None:
    seen: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_ok_body())

    client = TypeSafeClient(
        api_key="test-key",
        headers={"authorization": "Bearer default"},
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    client.system_one_sync(
        state={}, questions={"q": {"type": "noul"}}, headers={"AUTHORIZATION": "Bearer hijack"}
    )
    client.close()
    assert seen[0].headers.get_list("authorization") == ["Bearer test-key"]


def test_read_only_cache_miss_is_not_wrapped_or_retried(tmp_path) -> None:
    from systemoneprompts.cache import CacheMissError, create_caching_fetch
    from systemoneprompts.provider import wrap_caching_fetch

    calls = {"n": 0}

    def network(_url: str, _init: dict | None = None) -> object:
        calls["n"] += 1
        raise AssertionError("network must not be called")

    caching = create_caching_fetch(dir=str(tmp_path), mode="read-only", fetch=network)
    client = TypeSafeClient(
        api_key="test", transport=wrap_caching_fetch(caching), max_retries=2
    )
    started = time.monotonic()
    with pytest.raises(CacheMissError) as caught:
        client.system_one_sync(state={}, questions={"q": {"type": "noul"}})
    with pytest.raises(CacheMissError):
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert caught.value.ids == ["q"]
    assert calls["n"] == 0
    assert time.monotonic() - started < 0.3


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


def test_cloudflare_rejects_custom_base_url() -> None:
    with pytest.raises(TypeSafeClientError) as caught:
        TypeSafeClient(
            api_key="cf-token",
            cloudflare_account_id="acct",
            base_url="https://openrouter.ai/api",
            transport=httpx2.MockTransport(lambda r: httpx2.Response(200)),
        )
    assert caught.value.diagnostic.code == "cloudflare-base-url"


def test_cloudflare_posts_envelope_and_unwraps_result() -> None:
    seen: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            json={
                "success": True,
                "errors": [],
                "result": {
                    "state": "Completed",
                    "result": _ok_body(0.8),
                    "gatewayMetadata": {"keySource": "BYOK"},
                },
            },
        )

    client = TypeSafeClient(
        api_key="cf-token",
        cloudflare_account_id="acct-1",
        model="jev-1.13.0",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    result = asyncio.run(
        client.system_one(state={"text": "now"}, questions={"q": {"type": "noul"}})
    )
    client.close()
    assert result["answers"]["q"]["noul"] == 0.8
    assert result["model"] == "jev-test"
    assert "gatewayMetadata" not in result
    request = seen[0]
    request.read()
    assert str(request.url) == cloudflare_run_url("acct-1")
    assert request.headers.get("host") == "api.cloudflare.com"
    assert request.headers.get("authorization") == "Bearer cf-token"
    body = json.loads(request.content)
    assert body["model"] == CLOUDFLARE_MODEL
    assert body["input"]["state"] == {"text": "now"}
    assert "model" not in body["input"]


def test_cloudflare_error_message() -> None:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            402,
            json={
                "success": False,
                "errors": [
                    {
                        "code": 2021,
                        "message": "Insufficient balance; add money to your gateway or use BYOK",
                    }
                ],
                "result": {},
            },
        )

    client = TypeSafeClient(
        api_key="cf-token",
        cloudflare_account_id="acct-1",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    with pytest.raises(TypeSafeHttpError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert caught.value.status == 402
    assert "Insufficient balance" in str(caught.value)


def test_openrouter_extra_fields_are_stripped() -> None:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "gen-1",
                "provider": "TypeSafe",
                "model": "typesafe/jev-1.13",
                "answers": {"q": {"type": "noul", "noul": 0.7}},
                "usage": {"input_tokens": 1, "output_tokens": 1, "cost": 0.00001},
            },
        )

    client = TypeSafeClient(
        api_key="or-key",
        base_url="https://openrouter.ai/api",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    result = asyncio.run(client.system_one(state="hi", questions={"q": {"type": "noul"}}))
    client.close()
    assert result["model"] == "typesafe/jev-1.13"
    assert set(result) == {"model", "answers", "usage"}
    assert result["usage"]["input_tokens"] == 1


def _cf_ok(noul: float = 0.7) -> dict[str, object]:
    return {
        "success": True,
        "result": {"state": "Completed", "result": _ok_body(noul)},
    }


def test_cloudflare_empty_api_key_falls_back_to_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "from-env")
    seen: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx2.Response(200, json=_cf_ok())

    client = TypeSafeClient(
        api_key="",
        cloudflare_account_id="acct-1",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert seen == ["Bearer from-env"]


def test_cloudflare_preserves_401() -> None:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401,
            json={"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]},
        )

    client = TypeSafeClient(
        api_key="cf-token",
        cloudflare_account_id="acct-1",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    with pytest.raises(TypeSafeHttpError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert caught.value.status == 401
    assert "Authentication error" in str(caught.value)


def test_cloudflare_200_error_envelope_becomes_400() -> None:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"success": False, "errors": [{"message": "nope"}]})

    client = TypeSafeClient(
        api_key="cf-token",
        cloudflare_account_id="acct-1",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    with pytest.raises(TypeSafeHttpError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert caught.value.status == 400


def test_cloudflare_200_insufficient_balance_becomes_402() -> None:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "success": False,
                "errors": [{"code": 2021, "message": "Insufficient balance"}],
            },
        )

    client = TypeSafeClient(
        api_key="cf-token",
        cloudflare_account_id="acct-1",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    with pytest.raises(TypeSafeHttpError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert caught.value.status == 402
    assert "Insufficient balance" in str(caught.value)


def test_cloudflare_incomplete_job_is_502() -> None:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"success": True, "result": {"state": "Running"}})

    client = TypeSafeClient(
        api_key="cf-token",
        cloudflare_account_id="acct-1",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    with pytest.raises(TypeSafeHttpError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert caught.value.status == 502


def test_cloudflare_unrecognized_success_is_502() -> None:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"success": True, "result": {"state": "Completed"}})

    client = TypeSafeClient(
        api_key="cf-token",
        cloudflare_account_id="acct-1",
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    with pytest.raises(TypeSafeHttpError) as caught:
        asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert caught.value.status == 502


def test_cloudflare_rejects_http_client() -> None:
    http = httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(200)))
    try:
        with pytest.raises(TypeSafeClientError) as caught:
            TypeSafeClient(
                api_key="cf-token",
                cloudflare_account_id="acct",
                http_client=http,
            )
        assert caught.value.diagnostic.code == "cloudflare-http-client"
    finally:
        http.close()


def test_cloudflare_forwards_timeout_extensions() -> None:
    seen: list[object] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(dict(request.extensions))
        return httpx2.Response(200, json=_cf_ok())

    client = TypeSafeClient(
        api_key="cf-token",
        cloudflare_account_id="acct-1",
        timeout=7,
        transport=httpx2.MockTransport(respond),
        max_retries=0,
    )
    asyncio.run(client.system_one(state={}, questions={"q": {"type": "noul"}}))
    client.close()
    assert seen
    assert seen[0] != {}
