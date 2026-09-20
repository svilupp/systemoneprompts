from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from systemoneprompts.client import TypeSafeClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _generated import load_generated  # noqa: E402

generated = load_generated(HERE, "routing_generated.py")


async def main() -> None:
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
