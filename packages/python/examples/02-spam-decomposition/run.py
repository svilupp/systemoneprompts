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
    generated = _generated("spam_generated.py")
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
