"""Run all three answer types with OPENAI_API_KEY."""
import asyncio
import json
from pathlib import Path

from ticket_generated import assert_state, evaluate_factors, questions

from systemoneprompts import OpenAIDecisionsClient
from systemoneprompts.provider import load_dotenv


async def main() -> None:
    load_dotenv()
    state = json.loads(Path(__file__).with_name("state.json").read_text())
    assert_state(state)
    client = OpenAIDecisionsClient()
    try:
        result = await client.system_one(state=state, questions=questions)
        print({**result, "factors": evaluate_factors(result["answers"])})
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
