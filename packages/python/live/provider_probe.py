"""One live provider variation; invoked by tools/run-live-providers.py."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import httpx2

from systemoneprompts import CloudflareDecisionsClient, OpenAIDecisionsClient, partition_answers
from systemoneprompts.client import TypeSafeClient
from systemoneprompts.dev import (
    create_cached_cloudflare_decisions_client,
    create_cached_openai_decisions_client,
)
from systemoneprompts.openrouter import openrouter_cache_dir
from systemoneprompts.provider import caching_httpx_transport


class CountingTransport(httpx2.BaseTransport):
    def __init__(self) -> None:
        self.inner = httpx2.HTTPTransport()
        self.calls = 0

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


def main() -> int:
    config = json.load(sys.stdin)
    with tempfile.TemporaryDirectory(prefix="provider-live-") as directory:
        transport = CountingTransport()
        common = {"transport": transport, "timeout": 20, "max_retries": 0, "model": config["model"]}
        if config["mode"] == "explicit":
            common.update(api_key=os.environ[config["key"]], base_url=config["baseURL"])
        network = None
        cached = None
        try:
            if config["provider"] == "openai":
                network = OpenAIDecisionsClient(**common)
                cached = create_cached_openai_decisions_client(client=network, dir=directory)
                client = cached["client"]
            elif config["provider"] == "cloudflare":
                network = CloudflareDecisionsClient(**common)
                cached = create_cached_cloudflare_decisions_client(client=network, dir=directory)
                client = cached["client"]
            else:
                router = config["provider"] == "openrouter"
                cache_dir = openrouter_cache_dir(dir=directory, base_url=config["baseURL"]) if router else str(Path(directory) / "cache")
                # Legacy Cloudflare must be inside the cache.
                if config["provider"] == "cloudflare-jev":
                    from systemoneprompts.cloudflare import create_cloudflare_transport
                    inner = create_cloudflare_transport(os.environ["CLOUDFLARE_ACCOUNT_ID"], inner=transport)
                else:
                    inner = transport
                cached_transport, _ = caching_httpx_transport(directory=cache_dir, inner=inner)
                common["transport"] = cached_transport
                network = TypeSafeClient(provider="openrouter" if router else "typesafe", **common)
                client = network

            async def run():
                request = {"state": config["state"], "questions": config["questions"]}
                started = time.perf_counter()
                result = await client.system_one(**request)
                latency_ms = (time.perf_counter() - started) * 1000
                hit = await client.system_one(**request)
                partition = partition_answers(config["questions"], result["answers"])
                assert not partition["missing"] and not partition["malformed"], "Missing or malformed native answers"
                assert hit["answers"] == result["answers"], "Cached answers changed"
                assert hit["usage"] == {"input_tokens": 0, "output_tokens": 0}, "Nonzero all-hit usage"
                assert transport.calls == 1, "Cache did not eliminate repeated network call"
                return result, latency_ms

            result, latency_ms = asyncio.run(run())
            print(json.dumps({"status": "pass", "model": result["model"], "usage": result["usage"], "answers": result["answers"], "networkCalls": transport.calls, "latencyMs": round(latency_ms, 3)}))
            return 0
        except Exception as error:
            print(json.dumps({"status": "fail", "error": type(error).__name__, "kind": getattr(error, "kind", None), "httpStatus": getattr(error, "status", None), "message": str(error)}))
            return 1
        finally:
            if cached:
                cached["client"].close()
            if network:
                network.close()


if __name__ == "__main__":
    raise SystemExit(main())
