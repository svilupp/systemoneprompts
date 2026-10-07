"""Worker for tools/check-cache-parity.py; no live network calls."""
import asyncio
import json
import sys
from dataclasses import asdict

import httpx2

from provider_fixtures import provider_fixtures
from systemoneprompts import CloudflareDecisionsClient, OpenAIDecisionsClient
from systemoneprompts.dev import (
    create_cached_cloudflare_decisions_client,
    create_cached_openai_decisions_client,
)

root, action, provider = sys.argv[1:]
assert provider in ("openai", "cloudflare")
cloudflare = provider == "cloudflare"
fixture = provider_fixtures(f"{provider}-decisions")[0]
calls = []


def handle(request):
    calls.append(request)
    assert action == "write", "read-only called network"
    endpoint = "https://api.cloudflare.com/client/v4/accounts/fixture-account/ai/run/@cf/cloudflare/clef" if cloudflare else "https://api.openai.com/v1/decisions"
    assert str(request.url) == endpoint
    assert json.loads(request.content) == fixture["request"]
    return httpx2.Response(200, json=fixture["response"])


cls = CloudflareDecisionsClient if cloudflare else OpenAIDecisionsClient
raw = cls(api_key="fixture", transport=httpx2.MockTransport(handle), **({"account_id": "fixture-account"} if cloudflare else {}))
make = create_cached_cloudflare_decisions_client if cloudflare else create_cached_openai_decisions_client
made = make(client=raw, dir=root, mode="read-write" if action == "write" else "read-only")
try:
    result = asyncio.run(made["client"].system_one(state=fixture["state"], questions=fixture["questions"]))
    assert result["answers"] == fixture["result"]["answers"]
    if action == "read":
        assert not calls
        assert result["usage"] == {"input_tokens": 0, "output_tokens": 0}
    print(json.dumps({"calls": len(calls), "stats": asdict(made["cache"].stats())}))
finally:
    made["client"].close()
    raw.close()
