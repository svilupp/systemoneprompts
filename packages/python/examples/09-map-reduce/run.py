from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType

from systemoneprompts.cache import create_caching_fetch
from systemoneprompts.client import TypeSafeClient
from systemoneprompts.patterns import run_many
from systemoneprompts.provider import load_dotenv, wrap_caching_fetch

HERE = Path(__file__).resolve().parent


def _generated(name: str) -> ModuleType:
    path = HERE / name
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load generated module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def main() -> None:
    load_dotenv(str(HERE.parents[1]))
    generated = _generated("batch_generated.py")
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
