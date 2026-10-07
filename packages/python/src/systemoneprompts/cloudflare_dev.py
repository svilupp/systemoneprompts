"""Development-only factories; reuse the canonical per-question System One cache."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import math
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, TypedDict

from .cache import CacheMode, CachingFetch, FetchResponse, create_caching_fetch
from .cloudflare_decisions import CloudflareDecisionsClient
from .cloudflare_decisions_codec import (
    _encode,
    _incompatible,
    _is_valid_decisions_answer,
    _model,
    _normalize_base_url,
    _validate_normalized_result,
)
from .json_values import js_json_dumps, parse_json


def cloudflare_cache_dir(
    *,
    dir: str | None = None,
    base_url: str | None = None,
    account_id: str | None = None,
    cwd: str | None = None,
) -> str:
    """`dir` is a root; append provider, adapter version, base URL hash, and cache."""
    account = (account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if base_url is None and not account:
        _incompatible(
            "missing-account", "CLOUDFLARE_ACCOUNT_ID is required to resolve the cache scope"
        )
    root = Path(dir) if dir is not None else Path(cwd or Path.cwd()) / ".systemoneprompts"
    origin = hashlib.sha256(_normalize_base_url(base_url, account).encode("utf-8")).hexdigest()
    return str(root / "providers" / "cloudflare-decisions" / "v1" / origin / "cache")


class CachedCloudflareDecisionsClient:
    def __init__(self, network: CloudflareDecisionsClient, cache: CachingFetch) -> None:
        self._network = network
        self._cache = cache
        # Cache workers may wait on the async client's normal executor. A separate
        # pool prevents many concurrent cache misses from exhausting that executor.
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="decisions-cache")

    async def system_one(
        self,
        *,
        state: Any,
        questions: Any,
        model: str | None = None,
        timeout: Any = None,
        headers: Any = None,
    ) -> dict[str, Any]:
        if isinstance(timeout, (int, float)) and (
            type(timeout) is bool or not math.isfinite(timeout) or timeout <= 0
        ):
            _incompatible("cloudflare-options", "timeout must be positive")
        actual_model = _model(self._network.default_model if model is None else model)
        _encode(state, questions, actual_model)
        snapshot = copy.deepcopy({"state": state, "questions": questions, "model": actual_model})
        cancelled = threading.Event()
        pending: list[Future[Any]] = []
        loop = asyncio.get_running_loop()
        options = {
            "method": "POST",
            "body": js_json_dumps(snapshot),
            "_loop": loop,
            "_call_options": {"timeout": timeout, "headers": headers},
            "_cancelled": cancelled,
            "_pending": pending,
        }
        try:
            response = await loop.run_in_executor(
                self._executor,
                partial(self._cache, "https://systemoneprompts.invalid/v1/systemone", options),
            )
        except asyncio.CancelledError:
            cancelled.set()
            for future in pending:
                future.cancel()
            raise
        return _validate_normalized_result(response.json(), snapshot["questions"])

    def close(self) -> None:
        """Release factory-owned cache workers; the supplied network client stays caller-owned."""
        self._executor.shutdown(wait=False, cancel_futures=True)


class CachedCloudflareConstruction(TypedDict):
    client: CachedCloudflareDecisionsClient
    cache: CachingFetch


def create_cached_cloudflare_decisions_client(
    *, client: CloudflareDecisionsClient, dir: str | None = None, mode: CacheMode = "read-write"
) -> CachedCloudflareConstruction:
    if mode not in ("read-write", "read-only", "refresh"):
        _incompatible("cloudflare-cache-mode", "Unknown cache mode")

    def adapter(_url: str, init: Any = None) -> FetchResponse:
        request = parse_json(init["body"])
        if init["_cancelled"].is_set():
            raise asyncio.CancelledError()
        future = asyncio.run_coroutine_threadsafe(
            client.system_one(**request, **init["_call_options"]), init["_loop"]
        )
        init["_pending"].append(future)
        if init["_cancelled"].is_set():
            future.cancel()
        result = future.result()
        return FetchResponse(status=200, body=js_json_dumps(result).encode("utf-8"))

    caching = create_caching_fetch(
        dir=cloudflare_cache_dir(dir=dir, base_url=client.base_url),
        mode=mode,
        fetch=adapter,
        validate_entry=_is_valid_decisions_answer,
    )
    return {"client": CachedCloudflareDecisionsClient(client, caching), "cache": caching}


__all__ = ["create_cached_cloudflare_decisions_client", "cloudflare_cache_dir"]
