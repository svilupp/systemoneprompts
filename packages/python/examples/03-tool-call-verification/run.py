from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from systemoneprompts.client import TypeSafeClient
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
    generated = _generated("verify_generated.py")
    state = json.loads((HERE / "states" / "trace.json").read_text(encoding="utf-8"))
    generated.assert_state(state)

    client = TypeSafeClient()
    try:
        response = await client.system_one(
            state=state, questions=generated.questions, model=generated.model
        )
        print({"answers": response["answers"], "factors": generated.evaluate_factors(response["answers"])})
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
