from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from systemoneprompts.client import TypeSafeClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _generated import load_generated  # noqa: E402

generated = load_generated(HERE, "triage_generated.py")


async def main() -> None:
    state = json.loads((HERE / "states" / "ticket.json").read_text(encoding="utf-8"))
    generated.assert_state(state)

    client = TypeSafeClient()
    try:
        response = await client.system_one(
            state=state, questions=generated.questions, model=generated.model
        )
        answers = response["answers"]
        factors = generated.evaluate_factors(answers)

        spam_risk = (
            0.45 * answers["requests_credentials"]["noul"]
            + 0.3 * answers["sender_identity_mismatch"]["noul"]
            + 0.25 * answers["unexpected_reward"]["noul"]
        )

        action = "account"
        if factors["spam.corroborated"] or spam_risk >= 0.6:
            action = "quarantine"
        elif not factors["topic.confident"] or (spam_risk > 0.4 and spam_risk < 0.6):
            action = "human_review"
        elif factors["topic.billing"]:
            action = "billing"
        elif factors["topic.orders"]:
            action = "orders"

        print(
            {
                "model": response["model"],
                "topic": answers["topic"]["choice"],
                "spamRisk": spam_risk,
                "factors": factors,
                "action": action,
                "usage": response["usage"],
            }
        )
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
