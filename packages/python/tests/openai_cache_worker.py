"""Worker for tools/check-openai-cache-parity.py; no live network calls."""
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

import httpx2

from systemoneprompts import OpenAIDecisionsClient
from systemoneprompts.dev import create_cached_openai_decisions_client

root, action = sys.argv[1:]
fixture = json.loads((Path(__file__).resolve().parents[1] / "conformance/v1/providers/openai-decisions.json").read_text())[0]
calls = []


def handle(request):
    calls.append(request)
    assert action == "write", "read-only called network"
    assert str(request.url) == "https://api.openai.com/v1/decisions"
    assert json.loads(request.content) == fixture["request"]
    return httpx2.Response(200, json=fixture["response"])


raw = OpenAIDecisionsClient(api_key="fixture", transport=httpx2.MockTransport(handle))
made = create_cached_openai_decisions_client(client=raw, dir=root, mode="read-write" if action == "write" else "read-only")
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
