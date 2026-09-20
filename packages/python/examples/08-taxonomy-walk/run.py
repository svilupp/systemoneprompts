from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType

from systemoneprompts.client import TypeSafeClient
from systemoneprompts.patterns import walk_taxonomy
from systemoneprompts.provider import load_dotenv

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
    generated = _generated("taxonomy_generated.py")
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
