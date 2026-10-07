"""Worker for tools/check-cloudflare-cache-parity.py; no live network calls."""

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

import httpx2

from systemoneprompts import CloudflareDecisionsClient
from systemoneprompts.dev import create_cached_cloudflare_decisions_client

root, action = sys.argv[1:]
fixture = json.loads(
    (
        Path(__file__).resolve().parents[1] / "conformance/v1/providers/cloudflare-decisions.json"
    ).read_text()
)[0]
calls = []


def handle(request):
    calls.append(request)
    assert action == "write", "read-only called network"
    assert (
        str(request.url)
        == "https://api.cloudflare.com/client/v4/accounts/fixture-account/ai/run/@cf/cloudflare/clef"
    )
    assert json.loads(request.content) == fixture["request"]
    return httpx2.Response(200, json=fixture["response"])


raw = CloudflareDecisionsClient(
    api_key="fixture", account_id="fixture-account", transport=httpx2.MockTransport(handle)
)
made = create_cached_cloudflare_decisions_client(
    client=raw, dir=root, mode="read-write" if action == "write" else "read-only"
)
try:
    result = asyncio.run(
        made["client"].system_one(state=fixture["state"], questions=fixture["questions"])
    )
    assert result["answers"] == fixture["result"]["answers"]
    if action == "read":
        assert not calls
        assert result["usage"] == {"input_tokens": 0, "output_tokens": 0}
    print(json.dumps({"calls": len(calls), "stats": asdict(made["cache"].stats())}))
finally:
    made["client"].close()
    raw.close()
