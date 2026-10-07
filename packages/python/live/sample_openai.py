"""Explicit labeled sample; --compare also calls TypeSafe when its key is available."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from systemoneprompts import OpenAIDecisionsClient, load_definition
from systemoneprompts.client import TypeSafeClient
from systemoneprompts.provider import load_dotenv


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(str(root.parents[1]))
    example = root / "examples/11-openai-decisions"
    definition = load_definition(example / "ticket.toml")
    cases = [json.loads(line) for line in (example / "cases.jsonl").read_text().splitlines()]
    clients = {"openai": OpenAIDecisionsClient(max_retries=0)}
    if args.compare and os.environ.get("TYPESAFE_API_KEY"):
        clients["typesafe"] = TypeSafeClient(max_retries=0)
    report = {
        "cases": [],
        "comparison": "TypeSafe key unavailable"
        if "typesafe" not in clients
        else "same requests on both providers",
    }
    try:
        for case in cases:
            item = {"id": case["id"], "labels": case["labels"], "providers": {}}
            if "note" in case:
                item["note"] = case["note"]
            for name, client in clients.items():
                item["providers"][name] = await client.system_one(
                    state=case["state"], questions=definition.questions
                )
            if "typesafe" in clients:
                a = item["providers"]["openai"]["answers"]
                b = item["providers"]["typesafe"]["answers"]
                item["differences_openai_minus_typesafe"] = {
                    "duplicate_probability": a["duplicate"]["noul"] - b["duplicate"]["noul"],
                    "department_probabilities": {
                        key: a["department"]["probabilities"][key]
                        - b["department"]["probabilities"][key]
                        for key in a["department"]["probabilities"]
                    },
                    "severity_score": a["severity"]["score"] - b["severity"]["score"],
                }
            report["cases"].append(item)
            args.report.write_text(json.dumps(report, indent=2) + "\n")
    finally:
        for client in clients.values():
            client.close()
    print(
        f"Labeled sample: {len(cases)} cases; providers {', '.join(clients)}; report {args.report}"
    )


if __name__ == "__main__":
    asyncio.run(main())
