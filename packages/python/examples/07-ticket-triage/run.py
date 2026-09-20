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
    generated = _generated("triage_generated.py")
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
