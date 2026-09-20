"""Cloudflare Workers AI System One adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlparse

CLOUDFLARE_MODEL = "typesafe/jev"
CLOUDFLARE_API_ORIGIN = "https://api.cloudflare.com"
SYSTEM_ONE_PATH = "/v1/systemone"


def cloudflare_run_url(account_id: str) -> str:
    return f"{CLOUDFLARE_API_ORIGIN}/client/v4/accounts/{quote(account_id, safe='')}/ai/run"


def wrap_cloudflare_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model": CLOUDFLARE_MODEL,
        "input": {"state": payload.get("state"), "questions": payload.get("questions")},
    }


def cloudflare_error_message(body: Any) -> str | None:
    if not isinstance(body, Mapping):
        return None
    errors = body.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    first = errors[0]
    if isinstance(first, Mapping):
        message = first.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None


def cloudflare_failure_status(body: Any, http_status: int | None = None) -> int | None:
    if not isinstance(body, Mapping):
        return None
    if body.get("success") is False:
        if http_status is not None and (http_status < 200 or http_status >= 300):
            return http_status
        errors = body.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], Mapping):
            if errors[0].get("code") == 2021:
                return 402
        return 400
    result = body.get("result")
    if isinstance(result, Mapping):
        state = result.get("state")
        if isinstance(state, str) and state != "Completed":
            return 502
    return None


def unwrap_cloudflare_result(parsed: Any) -> dict[str, Any] | None:
    if not isinstance(parsed, Mapping):
        return None
    if isinstance(parsed.get("answers"), Mapping):
        return dict(parsed)
    outer = parsed.get("result")
    if not isinstance(outer, Mapping):
        return None
    if isinstance(outer.get("answers"), Mapping):
        return dict(outer)
    inner = outer.get("result")
    if isinstance(inner, Mapping) and isinstance(inner.get("answers"), Mapping):
        return dict(inner)
    return None


def is_system_one_url(url: str) -> bool:
    try:
        return urlparse(url).path.endswith(SYSTEM_ONE_PATH)
    except ValueError:
        return SYSTEM_ONE_PATH in url


HOP_BY_HOP = {"content-length", "content-encoding", "transfer-encoding"}


def _response_headers(response: Any) -> list[tuple[str, str]]:
    headers = getattr(response, "headers", None)
    if headers is None:
        return []
    items = headers.items() if hasattr(headers, "items") else headers
    return [(key, value) for key, value in items if str(key).lower() not in HOP_BY_HOP]


def create_cloudflare_transport(account_id: str, inner: Any = None) -> Any:
    import httpx2

    account_id = account_id.strip()
    owned = inner is None
    forward = inner if inner is not None else httpx2.HTTPTransport()

    class CloudflareRewriteTransport(httpx2.BaseTransport):  # type: ignore[misc, unused-ignore]
        systemoneprompts_cloudflare = True

        def handle_request(self, request: httpx2.Request) -> httpx2.Response:
            request.read()
            if not is_system_one_url(str(request.url)):
                return forward.handle_request(request)
            try:
                parsed = json.loads(request.content.decode("utf-8"))
            except Exception:
                return forward.handle_request(request)
            if not isinstance(parsed, Mapping) or not isinstance(parsed.get("questions"), Mapping):
                return forward.handle_request(request)
            headers = {
                key: value
                for key, value in request.headers.items()
                if key.lower()
                not in {
                    "host",
                    "content-length",
                    "content-encoding",
                    "transfer-encoding",
                    "connection",
                    "keep-alive",
                    "te",
                    "trailer",
                    "upgrade",
                }
            }
            rewritten = httpx2.Request(
                "POST",
                cloudflare_run_url(account_id),
                headers=headers,
                json=wrap_cloudflare_request(parsed),
                extensions=dict(getattr(request, "extensions", {}) or {}),
            )
            response = forward.handle_request(rewritten)
            response.read()
            try:
                body = response.json()
            except Exception:
                return response
            status = int(getattr(response, "status_code", 0) or 0)
            failure = cloudflare_failure_status(body, status)
            out_headers = _response_headers(response)
            if failure is not None:
                return httpx2.Response(
                    failure, json=body, request=request, headers=out_headers
                )
            if 200 <= status < 300:
                unwrapped = unwrap_cloudflare_result(body)
                if unwrapped is not None:
                    return httpx2.Response(
                        200, json=unwrapped, request=request, headers=out_headers
                    )
                return httpx2.Response(502, json=body, request=request, headers=out_headers)
            return response

        def close(self) -> None:
            if owned:
                closer = getattr(forward, "close", None)
                if callable(closer):
                    closer()

    return CloudflareRewriteTransport()


__all__ = [
    "CLOUDFLARE_API_ORIGIN",
    "CLOUDFLARE_MODEL",
    "cloudflare_error_message",
    "cloudflare_failure_status",
    "cloudflare_run_url",
    "create_cloudflare_transport",
    "is_system_one_url",
    "unwrap_cloudflare_result",
    "wrap_cloudflare_request",
]
