"""Explicit live checks for both Clef models; never part of offline checks."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from systemoneprompts import CloudflareDecisionsClient, load_definition, partition_answers
from systemoneprompts.dev import create_cached_cloudflare_decisions_client
from systemoneprompts.provider import load_dotenv

load_dotenv()


@pytest.mark.skipif(
    not os.environ.get("CLOUDFLARE_API_TOKEN") or not os.environ.get("CLOUDFLARE_ACCOUNT_ID"),
    reason="Cloudflare credentials not set",
)
@pytest.mark.parametrize("model", ["clef", "clef-flash"])
def test_cloudflare_all_types(tmp_path, model):
    root = Path(__file__).resolve().parents[1] / "examples/12-cloudflare-decisions"
    definition = load_definition(root / "ticket.toml")
    network = CloudflareDecisionsClient(model=model, max_retries=0)
    made = create_cached_cloudflare_decisions_client(client=network, dir=str(tmp_path))

    async def run():
        request = {
            "state": json.loads((root / "state.json").read_text()),
            "questions": definition.questions,
        }
        result = await made["client"].system_one(**request)
        hit = await made["client"].system_one(**request)
        partition = partition_answers(definition.questions, result["answers"])
        assert not partition["missing"] and not partition["malformed"]
        assert result["model"] == model
        assert result["usage"]["output_tokens"] == 0
        assert hit["answers"] == result["answers"]
        assert hit["usage"] == {"input_tokens": 0, "output_tokens": 0}
        assert made["cache"].stats().hits == 3
        assert made["cache"].stats().misses == 3

    try:
        asyncio.run(run())
    finally:
        made["client"].close()
        network.close()
