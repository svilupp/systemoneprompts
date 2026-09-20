from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from systemoneprompts.client import TypeSafeClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _generated import load_generated  # noqa: E402

generated = load_generated(HERE, "spam_generated.py")


async def main() -> None:
    state = json.loads((HERE / "states" / "phish.json").read_text(encoding="utf-8"))
    generated.assert_state(state)

    client = TypeSafeClient()
    try:
        response = await client.system_one(
            state=state, questions=generated.questions, model=generated.model
        )
        factors = generated.evaluate_factors(response["answers"])
        answers = response["answers"]
        spam_risk = (
            0.45 * answers["requests_credentials"]["noul"]
            + 0.3 * answers["sender_identity_mismatch"]["noul"]
            + 0.25 * answers["unexpected_reward"]["noul"]
        )
        print(
            {
                "broad": answers["broad_spam"]["noul"],
                "decomposed": {
                    "requests_credentials": answers["requests_credentials"]["noul"],
                    "sender_identity_mismatch": answers["sender_identity_mismatch"]["noul"],
                    "unexpected_reward": answers["unexpected_reward"]["noul"],
                },
                "factors": factors,
                "spamRisk": spam_risk,
            }
        )
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
