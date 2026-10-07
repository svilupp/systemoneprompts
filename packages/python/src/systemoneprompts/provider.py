"""Live TypeSafe client helpers. HTTP lives in `client.py` (pydantic + httpx2)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict

import httpx2

from .cache import (
    CachingFetch,
    FetchResponse,
    create_caching_fetch,
    default_cache_dir,
    transport_headers,
)
from .client import TypeSafeClient, TypeSafeClientError
from .cloudflare import create_cloudflare_transport
from .definition import Definition
from .dev import create_cached_openai_decisions_client
from .diagnostics import SystemOnePromptsError, diagnostic
from .model import read_env_model, resolve_model
from .openai_decisions import OpenAIDecisionsClient, OpenAIDecisionsError
from .patterns import SystemOneClient


class ClientConstruction(TypedDict):
    client: SystemOneClient
    model: str
    cache: CachingFetch | None
    raw: TypeSafeClient | OpenAIDecisionsClient


class LiveClientError(SystemOnePromptsError):
    pass


def load_dotenv(cwd: str | None = None) -> None:
    path = Path(cwd or os.getcwd()) / ".env"
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        eq = trimmed.find("=")
        if eq <= 0:
            continue
        key = trimmed[:eq].strip()
        value = trimmed[eq + 1 :].strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def native_result(response: Any) -> dict[str, Any]:
    """Normalize a System One or fake response to `{model, answers, usage}`."""
    if isinstance(response, Mapping):
        answers = response.get("answers")
        usage = response.get("usage") or {}
        return {
            "model": response.get("model"),
            "answers": _dump_answers(answers),
            "usage": {
                "input_tokens": usage.get("input_tokens") if isinstance(usage, Mapping) else None,
                "output_tokens": usage.get("output_tokens") if isinstance(usage, Mapping) else None,
            },
        }
    if not hasattr(response, "answers"):
        raise TypeError(
            "System One response must be a mapping or an object with `answers`, "
            f"got {type(response).__name__}"
        )
    answers = response.answers
    usage = getattr(response, "usage", None)
    dumped = _dump_answers(answers)
    return {
        "model": getattr(response, "model", None),
        "answers": dumped,
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None) if usage is not None else None,
            "output_tokens": getattr(usage, "output_tokens", None) if usage is not None else None,
        },
    }


def _dump_answers(answers: Any) -> dict[str, Any]:
    if not isinstance(answers, Mapping):
        return {}
    output: dict[str, Any] = {}
    for key, value in answers.items():
        if hasattr(value, "model_dump"):
            dumped = value.model_dump(mode="json")
            output[str(key)] = dumped
        elif isinstance(value, Mapping):
            output[str(key)] = dict(value)
        else:
            output[str(key)] = value
    return output


class FakeClient:
    """Deterministic client for tests: records calls and returns scripted answers."""

    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    async def system_one(
        self,
        *,
        state: Any,
        questions: Mapping[str, Any],
        model: str | None = None,
    ) -> dict[str, Any]:
        request = {"state": state, "questions": dict(questions), "model": model}
        self.calls.append(request)
        result = self.handler(request)
        if hasattr(result, "__await__"):
            result = await result
        if isinstance(result, BaseException):
            raise result
        return native_result(result)


def create_client(
    definition: Definition,
    *,
    cache: bool = False,
    provider: str | None = None,
    model: str | None = None,
    env: Mapping[str, str | None] | None = None,
    transport: Any = None,
    http_client: Any = None,
    cache_dir: str | None = None,
    cache_root: str | None = None,
    cache_fetch: Any = None,
) -> ClientConstruction:
    """Build a live client. Invalid definitions/state must be checked by the caller first.

    With `cache=True`, requests flow through the canonical per-question cache.
    TypeSafe misses use `cache_fetch`, the caller's `transport`, or a fresh
    `httpx2.HTTPTransport`; a TypeSafe caller `http_client` cannot be combined
    with caching. OpenAI wraps its raw client with the dev cache factory and
    supports caller-owned HTTP clients. `cache_fetch` is TypeSafe-only.
    """
    load_dotenv()
    selected = provider if provider is not None else definition.provider or "typesafe"
    if selected not in ("typesafe", "openai"):
        raise LiveClientError(diagnostic("error", "provider-value", 'provider must be "typesafe" or "openai"'))
    if selected == "openai":
        if model is not None and not model.strip():
            raise LiveClientError(diagnostic("error", "openai-model-empty", "model must be nonblank"))
        if cache and cache_fetch is not None:
            raise LiveClientError(diagnostic("error", "openai-cache-transport", "Use the dev factory with a raw OpenAI client; cache_fetch is a TypeSafe transport option"))
        resolved = resolve_model(None, definition.model, model, default="gpt-6-luna")
        try:
            client_openai = OpenAIDecisionsClient(model=resolved, transport=transport, http_client=http_client, environ=env)
        except OpenAIDecisionsError as error:
            raise LiveClientError(error.diagnostic) from error
        if cache:
            cached = create_cached_openai_decisions_client(client=client_openai, dir=cache_root if cache_root is not None else cache_dir)
            return {"client": cached["client"], "model": resolved, "cache": cached["cache"], "raw": client_openai}
        return {"client": client_openai, "model": resolved, "cache": None, "raw": client_openai}
    resolved = resolve_model(read_env_model(env), definition.model, model)
    source = env if env is not None else os.environ
    cloudflare_account_id = (source.get("CLOUDFLARE_ACCOUNT_ID") or "").strip() or None
    if cloudflare_account_id and (source.get("TYPESAFE_BASE_URL") or "").strip():
        raise LiveClientError(
            diagnostic(
                "error",
                "cloudflare-base-url",
                "CLOUDFLARE_ACCOUNT_ID cannot be combined with TYPESAFE_BASE_URL",
            )
        )
    if cloudflare_account_id:
        api_key = source.get("CLOUDFLARE_API_TOKEN")
    else:
        api_key = source.get("TYPESAFE_API_KEY")
    provided_transport = transport is not None or http_client is not None
    caching: CachingFetch | None = None
    if cache:
        if http_client is not None:
            raise LiveClientError(
                diagnostic(
                    "error",
                    "cache-transport",
                    "cache=True cannot wrap a caller-supplied http_client; pass transport= instead",
                )
            )
        directory = cache_dir or (str(Path(cache_root) / "cache") if cache_root is not None else default_cache_dir())
        if cache_fetch is not None and cloudflare_account_id:
            raise LiveClientError(
                diagnostic(
                    "error",
                    "cloudflare-cache",
                    "cache_fetch cannot be combined with CLOUDFLARE_ACCOUNT_ID",
                )
            )
        if cache_fetch is not None:
            caching = create_caching_fetch(dir=directory, fetch=cache_fetch)
            transport = wrap_caching_fetch(caching)
        elif cloudflare_account_id:
            inner = create_cloudflare_transport(cloudflare_account_id, inner=transport)
            transport, caching = caching_httpx_transport(directory=directory, inner=inner)
        else:
            transport, caching = caching_httpx_transport(directory=directory, inner=transport)
    missing_key = not (isinstance(api_key, str) and api_key.strip())
    if missing_key and not provided_transport:
        raise LiveClientError(
            diagnostic(
                "error",
                "missing-credentials",
                "CLOUDFLARE_API_TOKEN is not set"
                if cloudflare_account_id
                else "TYPESAFE_API_KEY is not set",
                hint=(
                    "export CLOUDFLARE_API_TOKEN or place it in a local .env for live commands only"
                    if cloudflare_account_id
                    else "export TYPESAFE_API_KEY or place it in a local .env for live commands only"
                ),
            )
        )
    try:
        client = TypeSafeClient(
            api_key=str(api_key).strip() if not missing_key else None,
            base_url=None if cloudflare_account_id else (source.get("TYPESAFE_BASE_URL") or None),
            cloudflare_account_id=cloudflare_account_id,
            model=resolved,
            transport=transport,
            http_client=http_client,
            environ=source,
        )
    except TypeSafeClientError as error:
        raise LiveClientError(error.diagnostic) from error
    except Exception as error:
        raise LiveClientError(
            diagnostic("error", "provider-client", f"failed to construct TypeSafe client: {error}")
        ) from error
    return {"client": client, "model": resolved, "cache": caching, "raw": client}


def caching_httpx_transport(
    caching: CachingFetch | None = None,
    *,
    directory: str | None = None,
    inner: Any = None,
) -> Any:
    """Wrap a CachingFetch as an httpx2.BaseTransport.

    If `caching` is omitted, a cache is created that forwards misses through `inner`
    (an `httpx2.BaseTransport`), defaulting to a fresh `httpx2.HTTPTransport`.
    """
    owned_inner = None
    if caching is None:
        if inner is not None:
            forward = inner
            owned_inner = forward
        else:
            forward = httpx2.HTTPTransport()
            owned_inner = forward

        def http_fetch(url: str, init: Mapping[str, Any] | None = None) -> FetchResponse:
            options = dict(init or {})
            body = options.get("body")
            content = body.encode("utf-8") if isinstance(body, str) else body
            request = httpx2.Request(
                str(options.get("method") or "GET"),
                url,
                headers=transport_headers(options),
                content=content,
            )
            response = forward.handle_request(request)
            response.read()
            return FetchResponse(
                status=int(response.status_code),
                status_text=getattr(response, "reason_phrase", "OK") or "OK",
                headers={key.lower(): value for key, value in response.headers.items()},
                body=response.content,
            )

        caching = create_caching_fetch(dir=directory or default_cache_dir(), fetch=http_fetch)
    transport = wrap_caching_fetch(caching, inner=owned_inner)
    return transport, caching


def wrap_caching_fetch(caching: CachingFetch, inner: Any = None) -> Any:
    class CachingTransport(httpx2.BaseTransport):  # type: ignore[misc, unused-ignore]
        systemoneprompts_cache = True
        systemoneprompts_cloudflare = bool(
            getattr(inner, "systemoneprompts_cloudflare", False)
        )

        def handle_request(self, request: httpx2.Request) -> httpx2.Response:
            request.read()
            headers = {key: value for key, value in request.headers.items()}
            body = request.content.decode("utf-8") if request.content else None
            result = caching(
                str(request.url),
                {"method": request.method, "body": body, "headers": headers},
            )
            response_headers = [(key, value) for key, value in result.headers.items()]
            return httpx2.Response(
                result.status,
                headers=response_headers,
                content=result.body,
                request=request,
            )

        def close(self) -> None:
            closer = getattr(inner, "close", None)
            if callable(closer):
                closer()

    return CachingTransport()


__all__ = [
    "FakeClient",
    "LiveClientError",
    "caching_httpx_transport",
    "create_client",
    "load_dotenv",
    "native_result",
    "wrap_caching_fetch",
]
