from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from systemoneprompts.client import TypeSafeClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _generated import load_generated  # noqa: E402

generated = load_generated(HERE, "choice_generated.py")


async def main() -> None:
    state = json.loads((HERE / "states" / "policy.json").read_text(encoding="utf-8"))
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
