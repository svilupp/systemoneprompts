from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from systemoneprompts.client import TypeSafeClient
from systemoneprompts.patterns import walk_taxonomy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _generated import load_generated  # noqa: E402

generated = load_generated(HERE, "taxonomy_generated.py")


async def main() -> None:
    tree = {
        "Sporting Goods": {
            "Cycling": {
                "Bike Bottles & Cages": "Bottles and cages designed to mount on a bicycle",
            },
        },
        "Home & Kitchen": {
            "Drinkware": {
                "Water Bottles": "Everyday bottles for home or office use",
            },
        },
    }

    client = TypeSafeClient()
    try:
        paths = await walk_taxonomy(
            client,
            state={
                "listing": {
                    "title": "Insulated bike bottle with cage mounts",
                    "description": "Fits standard bicycle bottle cages. Leak-proof lid for rides.",
                },
            },
            instructions={
                "question": "Which category best fits this product listing?",
                "focus": "Prefer the path whose subtree matches the listing's intended use.",
            },
            tree=tree,
            beam_width=2,
            model=generated.model,
        )
        print(paths)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
