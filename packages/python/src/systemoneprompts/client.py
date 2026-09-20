"""Native TypeSafe System One / JEV HTTP client (pydantic + httpx2)."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any, Literal

from .cache import CacheMissError
from .cloudflare import (
    cloudflare_error_message,
    create_cloudflare_transport,
)
from .diagnostics import SystemOnePromptsError, diagnostic
from .model import DEFAULT_MODEL

LIVE_EXTRA = "systemoneprompts[live]"
DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_TIMEOUT = 10.0
SYSTEM_ONE_PATH = "/v1/systemone"
RETRY_STATUSES = frozenset({408, 429, *range(500, 600)})


def _trim_env(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _package_version() -> str:
    try:
        return version("systemoneprompts")
    except PackageNotFoundError:
        return "0.1.0"


class TypeSafeClientError(SystemOnePromptsError):
    pass


class TypeSafeHttpError(TypeSafeClientError):
    def __init__(
        self,
        status: int,
        body: Any,
        request_id: str | None = None,
        message: str | None = None,
        retry_after: float | None = None,
    ):
        suffix = f" (request {request_id})" if request_id else ""
        super().__init__(
            diagnostic(
                "error",
                "provider-http",
                message or f"TypeSafe API error {status}{suffix}",
            )
        )
        self.status = status
        self.body = body
        self.request_id = request_id
        self.retry_after = retry_after


class TypeSafeRateLimitError(TypeSafeHttpError):
    pass


def require_live() -> Any:
    try:
        import httpx2
        import pydantic as _pydantic
    except ImportError as error:
        raise TypeSafeClientError(
            diagnostic(
                "error",
                "missing-live",
                f"live commands require httpx2 and pydantic; install `{LIVE_EXTRA}`",
                hint="uv add 'systemoneprompts[live]' or pip install 'systemoneprompts[live]'",
            )
        ) from error
    _ = _pydantic.BaseModel
    return httpx2


def _models() -> Any:
    from pydantic import BaseModel, ConfigDict, Field

    class NoulAnswer(BaseModel):
        model_config = ConfigDict(extra="ignore")
        type: Literal["noul"]
        noul: float

    class ChoiceAnswer(BaseModel):
        model_config = ConfigDict(extra="ignore")
        type: Literal["choice"]
        choice: str
        confidence: float
        probabilities: dict[str, float]

    class ScoreAnswer(BaseModel):
        model_config = ConfigDict(extra="ignore")
        type: Literal["score"]
        score: float
        confidence: float
        legend: dict[str, Any]
        probabilities: dict[str, float]

    class Usage(BaseModel):
        model_config = ConfigDict(extra="ignore")
        input_tokens: int | None = None
        output_tokens: int | None = None

    Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]

    class SystemOneResponse(BaseModel):
        model_config = ConfigDict(extra="ignore")
        model: str
        answers: dict[str, Answer]
        usage: Usage = Field(default_factory=Usage)

    return SystemOneResponse


class TypeSafeClient:
    """Native HTTP client for TypeSafe System One.

    Pass `http_client` (an httpx2.Client or AsyncClient) when you need custom
    timeouts, proxies, or connection limits. Pass `transport` for tests and the
    per-question cache. `system_one` is async either way.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        cloudflare_account_id: str | None = None,
        model: str | None = None,
        timeout: float | Any | None = None,
        http_client: Any = None,
        transport: Any = None,
        headers: Mapping[str, str] | None = None,
        max_retries: int = 2,
        environ: Mapping[str, str | None] | None = None,
    ) -> None:
        httpx2 = require_live()
        import os

        source: Mapping[str, str | None] = os.environ if environ is None else environ
        account = (
            cloudflare_account_id.strip()
            if isinstance(cloudflare_account_id, str) and cloudflare_account_id.strip()
            else (source.get("CLOUDFLARE_ACCOUNT_ID") or "").strip() or None
        )
        explicit_base = base_url.strip() if isinstance(base_url, str) and base_url.strip() else None
        env_base = (source.get("TYPESAFE_BASE_URL") or "").strip() or None
        if account and (explicit_base or env_base):
            raise TypeSafeClientError(
                diagnostic(
                    "error",
                    "cloudflare-base-url",
                    "cloudflare_account_id cannot be combined with base_url or TYPESAFE_BASE_URL",
                )
            )
        self.cloudflare_account_id = account
        key = _trim_env(api_key)
        if key is None:
            if account:
                key = _trim_env(source.get("CLOUDFLARE_API_TOKEN")) or ""
            else:
                key = _trim_env(source.get("TYPESAFE_API_KEY")) or ""
        if not key and http_client is None and transport is None:
            raise TypeSafeClientError(
                diagnostic(
                    "error",
                    "missing-credentials",
                    "CLOUDFLARE_API_TOKEN is not set" if account else "TYPESAFE_API_KEY is not set",
                    hint=(
                        "export CLOUDFLARE_API_TOKEN or pass api_key"
                        if account
                        else "export TYPESAFE_API_KEY or place it in a local .env for live commands only"
                    ),
                )
            )
        self.api_key = key
        self.base_url = (explicit_base or env_base or DEFAULT_BASE_URL).rstrip("/")
        self.default_model = (
            model or source.get("TYPESAFE_DEFAULT_MODEL") or DEFAULT_MODEL
        ).strip() or DEFAULT_MODEL
        self.timeout = DEFAULT_TIMEOUT if timeout is None else timeout
        if type(max_retries) is not int or max_retries < 0:
            raise TypeSafeClientError(
                diagnostic("error", "provider-client", "max_retries must be >= 0")
            )
        self.max_retries = max_retries
        self.default_headers = {
            "Accept": "application/json",
            "User-Agent": f"systemoneprompts/{_package_version()}",
            **dict(headers or {}),
        }
        if key:
            self.default_headers["Authorization"] = f"Bearer {key}"
        self._owns_client = http_client is None
        self._async = False
        if account and http_client is not None:
            raise TypeSafeClientError(
                diagnostic(
                    "error",
                    "cloudflare-http-client",
                    "cloudflare_account_id cannot be combined with http_client; pass transport=",
                )
            )
        if account:
            if transport is None:
                transport = create_cloudflare_transport(account)
            elif getattr(transport, "systemoneprompts_cache", False) and not getattr(
                transport, "systemoneprompts_cloudflare", False
            ):
                raise TypeSafeClientError(
                    diagnostic(
                        "error",
                        "cloudflare-cache",
                        "cloudflare_account_id with a cache requires wrapping Cloudflare inside the cache",
                    )
                )
            elif not getattr(transport, "systemoneprompts_cloudflare", False):
                transport = create_cloudflare_transport(account, inner=transport)
        if http_client is not None:
            self._http = http_client
            request = getattr(http_client, "request", None)
            self._async = inspect.iscoroutinefunction(request)
            if not self._async:
                async_cls = getattr(httpx2, "AsyncClient", None)
                self._async = async_cls is not None and isinstance(http_client, async_cls)
        else:
            kwargs: dict[str, Any] = {"timeout": self.timeout, "headers": self.default_headers}
            if transport is not None:
                kwargs["transport"] = transport
            self._http = httpx2.Client(**kwargs)
        self._response_type = _models()

    def close(self) -> None:
        if self._owns_client:
            close = getattr(self._http, "close", None)
            if callable(close):
                close()

    async def system_one(
        self,
        *,
        state: Any,
        questions: Mapping[str, Any],
        model: str | None = None,
        timeout: float | Any | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        payload = self._payload(state, questions, model)
        if self._async:
            raw = await self._send_async(payload, timeout=timeout, headers=headers)
        else:
            raw = await asyncio.to_thread(self._send, payload, timeout, headers)
        return self._finalize(raw)

    def system_one_sync(
        self,
        *,
        state: Any,
        questions: Mapping[str, Any],
        model: str | None = None,
        timeout: float | Any | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        if self._async:
            raise TypeSafeClientError(
                diagnostic(
                    "error",
                    "provider-client",
                    "system_one_sync needs a sync httpx2.Client",
                )
            )
        return self._finalize(self._send(self._payload(state, questions, model), timeout, headers))

    def _payload(
        self, state: Any, questions: Mapping[str, Any], model: str | None
    ) -> dict[str, Any]:
        if not questions:
            raise TypeSafeClientError(
                diagnostic("error", "provider-client", "system_one requires at least one question")
            )
        return {
            "state": state,
            "questions": dict(questions),
            "model": self.default_model if model is None else model,
        }

    def _finalize(self, raw: Any) -> dict[str, Any]:
        try:
            parsed = self._response_type.model_validate(raw)
        except Exception as error:
            raise TypeSafeClientError(
                diagnostic("error", "provider-response", f"invalid System One response: {error}")
            ) from error
        dumped = parsed.model_dump(mode="json")
        return {
            "model": dumped.get("model"),
            "answers": dumped.get("answers") or {},
            "usage": dumped.get("usage") or {"input_tokens": None, "output_tokens": None},
        }

    def _send(
        self,
        payload: Mapping[str, Any],
        timeout: float | Any | None,
        headers: Mapping[str, str] | None,
    ) -> Any:
        return self._request_loop(payload, timeout, headers, async_mode=False)

    async def _send_async(
        self,
        payload: Mapping[str, Any],
        timeout: float | Any | None,
        headers: Mapping[str, str] | None,
    ) -> Any:
        return await self._request_loop(payload, timeout, headers, async_mode=True)

    def _request_loop(
        self,
        payload: Mapping[str, Any],
        timeout: float | Any | None,
        headers: Mapping[str, str] | None,
        *,
        async_mode: bool,
    ) -> Any:
        if async_mode:
            return self._request_loop_async(payload, timeout, headers)
        last_error: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._http.request(
                    "POST",
                    self.base_url + SYSTEM_ONE_PATH,
                    **self._request_kwargs(payload, timeout, headers),
                )
                return self._parse_response(response)
            except TypeSafeHttpError as error:
                last_error = error
                if attempt >= self.max_retries or error.status not in RETRY_STATUSES:
                    raise
                time.sleep(_retry_delay(attempt, error))
            except CacheMissError:
                raise  # a read-only cache transport already decided; never wrap or retry
            except Exception as error:
                last_error = error
                if attempt >= self.max_retries or not _is_retryable_connection(error):
                    raise _wrap_connection(error) from error
                time.sleep(_retry_delay(attempt))
        assert last_error is not None
        raise last_error

    async def _request_loop_async(
        self,
        payload: Mapping[str, Any],
        timeout: float | Any | None,
        headers: Mapping[str, str] | None,
    ) -> Any:
        last_error: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._http.request(
                    "POST",
                    self.base_url + SYSTEM_ONE_PATH,
                    **self._request_kwargs(payload, timeout, headers),
                )
                return self._parse_response(response)
            except TypeSafeHttpError as error:
                last_error = error
                if attempt >= self.max_retries or error.status not in RETRY_STATUSES:
                    raise
                await asyncio.sleep(_retry_delay(attempt, error))
            except CacheMissError:
                raise  # a read-only cache transport already decided; never wrap or retry
            except Exception as error:
                last_error = error
                if attempt >= self.max_retries or not _is_retryable_connection(error):
                    raise _wrap_connection(error) from error
                await asyncio.sleep(_retry_delay(attempt))
        assert last_error is not None
        raise last_error

    def _request_kwargs(
        self,
        payload: Mapping[str, Any],
        timeout: float | Any | None,
        headers: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "json": dict(payload),
            "headers": self._headers(headers),
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        elif self._owns_client:
            kwargs["timeout"] = self.timeout
        return kwargs

    def _headers(self, extra: Mapping[str, str] | None) -> dict[str, str]:
        merged = dict(self.default_headers)
        if extra:
            merged.update(extra)
        if self.api_key:
            # Header names are case-insensitive; a caller `authorization` must not merge with ours.
            for name in [name for name in merged if name.lower() == "authorization"]:
                del merged[name]
            merged["Authorization"] = f"Bearer {self.api_key}"
        return merged

    def _parse_response(self, response: Any) -> Any:
        request_id = None
        headers = getattr(response, "headers", None)
        if headers is not None:
            request_id = headers.get("x-typesafe-request-id")
        status = int(getattr(response, "status_code", 0) or 0)
        try:
            body = response.json()
        except Exception:
            body = getattr(response, "text", None)
        if 200 <= status < 300:
            return body
        message = None
        suffix = f" (request {request_id})" if request_id else ""
        if isinstance(body, str) and body.strip():
            message = f"TypeSafe API error {status}{suffix}: {body.strip()}"
        elif isinstance(body, Mapping):
            detail = (
                cloudflare_error_message(body)
                or body.get("error")
                or body.get("message")
            )
            if isinstance(detail, Mapping):
                detail = detail.get("message")
            if isinstance(detail, str) and detail:
                message = f"TypeSafe API error {status}{suffix}: {detail}"
        error_cls = TypeSafeRateLimitError if status == 429 else TypeSafeHttpError
        raise error_cls(
            status, body, request_id, message, retry_after=_retry_after_seconds(headers)
        )


def _retry_delay(attempt: int, error: TypeSafeHttpError | None = None) -> float:
    if error is not None and error.retry_after is not None:
        return min(max(error.retry_after, 0.0), 60.0)
    exponential = min(0.5 * float(2**attempt), 5.0)
    return float(exponential * 0.875)


def _retry_after_seconds(headers: Any) -> float | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    ms = getter("retry-after-ms")
    if ms is not None:
        try:
            value = float(ms)
        except (TypeError, ValueError):
            pass
        else:
            # Same as the TypeScript client: oversized milliseconds fall through to Retry-After.
            if 0 <= value <= 60_000:
                return value / 1000.0
    raw = getter("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        pass
    else:
        if seconds < 0:
            return None
        return min(seconds, 60.0)
    try:
        dt = parsedate_to_datetime(raw if isinstance(raw, str) else str(raw))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delay = (dt - datetime.now(UTC)).total_seconds()
    if delay < 0:
        return 0.0
    return min(delay, 60.0)


def _is_retryable_connection(error: BaseException) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return True
    name = type(error).__name__.lower()
    return any(
        token in name
        for token in ("timeout", "connect", "network", "transport", "readtimeout", "writetimeout")
    )


def _wrap_connection(error: BaseException) -> BaseException:
    name = type(error).__name__
    if "Timeout" in name:
        return TypeSafeClientError(
            diagnostic("error", "provider-timeout", str(error) or "TypeSafe API timed out")
        )
    if isinstance(error, TypeSafeClientError):
        return error
    return TypeSafeClientError(
        diagnostic("error", "provider-client", f"TypeSafe API connection error: {error}")
    )


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_TIMEOUT",
    "TypeSafeClient",
    "TypeSafeClientError",
    "TypeSafeHttpError",
    "TypeSafeRateLimitError",
    "require_live",
]
