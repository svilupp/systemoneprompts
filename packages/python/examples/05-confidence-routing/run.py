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
    generated = _generated("routing_generated.py")
    state = json.loads((HERE / "states" / "ticket.json").read_text(encoding="utf-8"))
    generated.assert_state(state)

    client = TypeSafeClient()
    try:
        response = await client.system_one(
            state=state, questions=generated.questions, model=generated.model
        )
        factors = generated.evaluate_factors(response["answers"])
        topic = response["answers"]["topic"]

        action = "route"
        if not factors["topic.confident"]:
            action = "human_review"
        elif factors["refund.gray"]:
            action = "ask_clarifying_question"
        elif topic["choice"] == "billing":
            action = "billing_queue"

        print(
            {
                "topic": topic["choice"],
                "confidence": topic["confidence"],
                "factors": factors,
                "action": action,
            }
        )
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
