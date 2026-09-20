from __future__ import annotations

import os

import pytest

from systemoneprompts import parse_definition
from systemoneprompts.provider import create_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("TYPESAFE_API_KEY"),
    reason="TYPESAFE_API_KEY is not set",
)


def test_live_system_one_returns_native_answers() -> None:
    definition = parse_definition(
        '[questions]\nurgent = { type = "noul", instructions = "Is this urgent?" }\n'
    )
    created = create_client(definition)
    import asyncio

    response = asyncio.run(
        created["client"].system_one(
            state={"text": "Please reply immediately"},
            questions=definition.questions,
            model=created["model"],
        )
    )
    assert "urgent" in response["answers"]
    assert response["answers"]["urgent"].get("type") == "noul"


def test_live_cache_forwards_misses(tmp_path) -> None:
    definition = parse_definition(
        '[questions]\nurgent = { type = "noul", instructions = "Is this urgent?" }\n'
    )
    cache_dir = tmp_path / ".systemoneprompts" / "cache"
    created = create_client(definition, cache=True, cache_dir=str(cache_dir))
    import asyncio

    first = asyncio.run(
        created["client"].system_one(
            state={"text": "Please reply immediately"},
            questions=definition.questions,
            model=created["model"],
        )
    )
    assert "urgent" in first["answers"]
    stats = created["cache"].stats()
    assert stats.misses >= 1
    second = asyncio.run(
        created["client"].system_one(
            state={"text": "Please reply immediately"},
            questions=definition.questions,
            model=created["model"],
        )
    )
    assert second["answers"]["urgent"] == first["answers"]["urgent"]
    assert created["cache"].stats().hits >= 1
