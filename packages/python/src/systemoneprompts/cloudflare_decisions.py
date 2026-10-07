"""Cloudflare Decisions REST adapter for the existing System One contract."""

from __future__ import annotations

import asyncio
import copy
import inspect
import math
import os
from collections.abc import Mapping
from typing import Any

import httpx2

from .client import _is_retryable_connection, _retry_after_seconds
from .cloudflare_decisions_codec import (
    CloudflareDecisionsError,
    _decode,
    _encode,
    _incompatible,
    _model,
    _normalize_base_url,
)
from .json_values import canonical_json


class CloudflareDecisionsClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        account_id: str | None = None,
        model: str | None = None,
        timeout: Any = None,
        http_client: Any = None,
        transport: Any = None,
        headers: Mapping[str, str] | None = None,
        max_retries: int = 2,
        environ: Mapping[str, str | None] | None = None,
    ):
        source = os.environ if environ is None else environ
        self.default_model = _model("clef" if model is None else model)
        self.api_key = (api_key or source.get("CLOUDFLARE_API_TOKEN") or "").strip()
        if not self.api_key and http_client is None and transport is None:
            _incompatible(
                "missing-credentials",
                "CLOUDFLARE_API_TOKEN is not set. Pass api_key or export CLOUDFLARE_API_TOKEN.",
            )
        self.account_id = (account_id or source.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
        if not self.account_id:
            _incompatible(
                "missing-account",
                "CLOUDFLARE_ACCOUNT_ID is not set. Pass account_id or export CLOUDFLARE_ACCOUNT_ID.",
            )
        self.base_url = _normalize_base_url(base_url, self.account_id)
        self.timeout = 10.0 if timeout is None else timeout
        if isinstance(self.timeout, (int, float)) and (
            type(self.timeout) is bool or not math.isfinite(self.timeout) or self.timeout <= 0
        ):
            _incompatible("cloudflare-options", "timeout must be positive")
        if type(max_retries) is not int or max_retries < 0:
            _incompatible("cloudflare-options", "max_retries must be a nonnegative integer")
        self.max_retries = max_retries
        if getattr(transport, "systemoneprompts_cache", False):
            _incompatible(
                "cloudflare-cache-transport",
                "Use create_cached_cloudflare_decisions_client instead of a caching transport as raw network I/O",
            )
        if transport is not None and http_client is not None:
            _incompatible("cloudflare-options", "transport cannot be combined with http_client")
        if transport is not None:
            # The HTTP client owns this proxy, while the supplied transport stays caller-owned.
            inner = transport

            class BorrowedTransport(httpx2.BaseTransport):
                def handle_request(self, request: Any) -> Any:
                    return inner.handle_request(request)

                def close(self) -> None:
                    pass

            transport = BorrowedTransport()
        self.default_headers = dict(headers or {})
        self._owns_client = http_client is None
        self._http: Any = (
            http_client
            if http_client is not None
            else httpx2.Client(timeout=self.timeout, transport=transport)
        )
        self._async = inspect.iscoroutinefunction(self._http.request)

    def close(self) -> None:
        if self._owns_client:
            closer = getattr(self._http, "close", None)
            if callable(closer):
                closer()

    async def system_one(
        self,
        *,
        state: Any,
        questions: Mapping[str, Any],
        model: str | None = None,
        timeout: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        snapshot = copy.deepcopy(questions)
        payload, ids = _encode(state, snapshot, self.default_model if model is None else model)
        content = canonical_json(payload).encode("utf-8")
        merged = {
            k: v
            for k, v in {**self.default_headers, **dict(headers or {})}.items()
            if k.lower() not in ("authorization", "content-type", "accept")
        }
        merged.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        actual_timeout = self.timeout if timeout is None else timeout
        if isinstance(actual_timeout, (int, float)) and (
            type(actual_timeout) is bool or not math.isfinite(actual_timeout) or actual_timeout <= 0
        ):
            _incompatible("cloudflare-options", "timeout must be positive")
        for attempt in range(self.max_retries + 1):
            retry_after = None
            try:
                kwargs: dict[str, Any] = {
                    "content": content,
                    "headers": merged,
                    "timeout": actual_timeout,
                }
                if self._async:
                    response = await self._http.request(
                        "POST", self.base_url + "/@cf/cloudflare/" + payload["model"], **kwargs
                    )
                else:
                    response = await asyncio.to_thread(
                        self._http.request,
                        "POST",
                        self.base_url + "/@cf/cloudflare/" + payload["model"],
                        **kwargs,
                    )
            except Exception as error:
                kind = (
                    "timeout"
                    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower()
                    else "transport"
                )
                if attempt >= self.max_retries or not _is_retryable_connection(error):
                    raise CloudflareDecisionsError(
                        f"Decisions connection failed: {error}", kind=kind, body=error
                    ) from error
            else:
                request_id = response.headers.get("cf-ray") or response.headers.get("x-request-id")
                try:
                    raw = response.json()
                except Exception:
                    raw = response.text
                status = response.status_code
                if 200 <= status < 300:
                    if isinstance(raw, dict) and raw.get("success") is False:
                        status = 400
                    else:
                        return _decode(raw, snapshot, ids, request_id)
                retry_after = _retry_after_seconds(response.headers)
                if (
                    attempt >= self.max_retries
                    or status not in (408, 429)
                    and not 500 <= status < 600
                ):
                    raise CloudflareDecisionsError(
                        f"Cloudflare Decisions HTTP {status}",
                        kind="http",
                        status=status,
                        body=raw,
                        request_id=request_id,
                        retry_after=retry_after,
                    )
            await asyncio.sleep(min(0.5 * 2**attempt, 5) if retry_after is None else retry_after)
        raise AssertionError("unreachable")


__all__ = ["CloudflareDecisionsClient", "CloudflareDecisionsError"]
