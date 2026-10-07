"""Explicit live smoke requiring only OPENAI_API_KEY."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from systemoneprompts import OpenAIDecisionsClient, load_definition, partition_answers
from systemoneprompts.dev import create_cached_openai_decisions_client
from systemoneprompts.provider import load_dotenv

load_dotenv()


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_openai_all_types(tmp_path):
    root = Path(__file__).resolve().parents[1] / "examples/11-openai-decisions"
    definition = load_definition(root / "ticket.toml")
    client = OpenAIDecisionsClient(max_retries=0)
    made = create_cached_openai_decisions_client(client=client, dir=str(tmp_path))
    async def run():
        request = {"state": json.loads((root / "state.json").read_text()), "questions": definition.questions}
        result = await made["client"].system_one(**request)
        hit = await made["client"].system_one(**request)
        partition = partition_answers(definition.questions, result["answers"])
        assert not partition["missing"]
        assert not partition["malformed"]
        assert result["usage"]["output_tokens"] == 0
        assert hit["answers"] == result["answers"]
        assert hit["usage"] == {"input_tokens": 0, "output_tokens": 0}
        assert made["cache"].stats().hits == 3
        assert made["cache"].stats().misses == 3
    try:
        asyncio.run(run())
    finally:
        made["client"].close()
        client.close()
