from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from systemoneprompts.cache import create_caching_fetch
from systemoneprompts.client import TypeSafeClient
from systemoneprompts.patterns import run_many
from systemoneprompts.provider import wrap_caching_fetch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _generated import load_generated  # noqa: E402

generated = load_generated(HERE, "batch_generated.py")


async def main() -> None:
    templates = [
        "I was charged twice for order A-{n}.",
        "Where is my order A-{n}?",
        "Reset my password, I cannot sign in.",
        "Please refund the duplicate charge.",
        "Cancel shipment A-{n} if it has not left.",
    ]
    states = [
        {"ticket": {"message": templates[i % len(templates)].replace("{n}", str(100 + i))}}
        for i in range(20)
    ]

    cache = create_caching_fetch()
    client = TypeSafeClient(transport=wrap_caching_fetch(cache))
    try:
        results = await run_many(
            client,
            questions=generated.questions,
            model=generated.model,
            states=states,
            concurrency=4,
        )
        counts = {"billing": 0, "orders": 0, "account": 0, "errors": 0}
        for result in results:
            if isinstance(result, Exception):
                counts["errors"] += 1
                continue
            counts[result["answers"]["topic"]["choice"]] += 1
        stats = cache.stats()
        print(
            {
                "processed": len(results),
                "counts": counts,
                "cache": {
                    "requests": stats.requests,
                    "hits": stats.hits,
                    "misses": stats.misses,
                    "keys": stats.keys,
                },
            }
        )
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
