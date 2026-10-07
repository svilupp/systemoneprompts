"""Explicit sequential live latency and cost comparison; no local cache or retries."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2

from systemoneprompts import OpenAIDecisionsClient, load_definition
from systemoneprompts.client import TypeSafeClient
from systemoneprompts.provider import load_dotenv

PRICES = {
    "openai": {
        "input_usd_per_million": 0.10,
        "output_usd_per_million": 0,
        "source": "https://developers.openai.com/api/docs/guides/decisions",
        "note": "Decisions-specific input-only rate; no separate cache-read/write or output charge. Standard short-context, nonregional pricing.",
    },
    "typesafe": {
        "input_usd_per_million": 0.042,
        "output_usd_per_million": 0,
        "source": "https://docs.typesafe.ai/models",
        "note": "Native Jev 1.13 input-token rate; output free.",
    },
}


class MeasuredHTTP:
    def __init__(self) -> None:
        self.client = httpx2.Client(timeout=30)
        self.last: dict[str, Any] = {}
        self.calls = 0

    def request(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self.last = {}
        start = time.perf_counter_ns()
        response = self.client.request(*args, **kwargs)
        elapsed = (time.perf_counter_ns() - start) / 1e6
        self.last = {
            "http_ms": elapsed,
            "status": response.status_code,
            "request_id": response.headers.get("x-request-id"),
        }
        try:
            self.last["raw_usage"] = response.json().get("usage")
        except (ValueError, AttributeError):
            pass
        return response

    def close(self) -> None:
        self.client.close()


def percentile(values: list[float], fraction: float) -> float:
    """Linear interpolation between adjacent sorted observations."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def summarize(rows: list[dict[str, Any]], provider: str) -> dict[str, Any]:
    attempts = [r for r in rows if r["provider"] == provider]
    ok = [r for r in attempts if "result" in r]
    if not ok:
        return {"attempts": len(attempts), "successes": 0}
    times = [r["elapsed_ms"] for r in ok]
    tokens = sum(r["result"]["usage"]["input_tokens"] for r in ok)
    cost = tokens * PRICES[provider]["input_usd_per_million"] / 1e6
    noul, choice, score = [], [], []
    for row in ok:
        answers, labels = row["result"]["answers"], row["labels"]
        if labels.get("duplicate") is not None:
            noul.append((answers["duplicate"]["noul"] >= 0.5) == labels["duplicate"])
        if labels.get("department") is not None:
            choice.append(answers["department"]["choice"] == labels["department"])
        if labels.get("severity") is not None:
            score.append(abs(answers["severity"]["score"] - labels["severity"]))
    return {
        "attempts": len(attempts), "successes": len(ok), "failures": len(attempts) - len(ok),
        "models": sorted({r["result"]["model"] for r in ok}),
        "latency_ms": {"mean": statistics.mean(times), "p50": percentile(times, 0.5),
                       "p95": percentile(times, 0.95), "min": min(times), "max": max(times),
                       "first_call": times[0], "warm_p50": percentile(times[1:], 0.5) if len(times) > 1 else None},
        "input_tokens": tokens, "mean_input_tokens": tokens / len(ok),
        "estimated_cost_usd": cost, "estimated_usd_per_1000_requests": cost / len(ok) * 1000,
        "estimated_usd_per_1000_decisions": cost / (len(ok) * 3) * 1000,
        "quality": {"noul_correct_at_0_5": sum(noul), "noul_labeled_count": len(noul),
                    "choice_correct": sum(choice), "choice_labeled_count": len(choice),
                    "score_mean_absolute_error": statistics.mean(score), "score_labeled_count": len(score)},
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 3:
        parser.error("at least 3 rounds are required (21 calls per provider)")
    root = Path(__file__).resolve().parents[1]
    load_dotenv(str(root.parents[1]))
    if os.environ.get("CLOUDFLARE_ACCOUNT_ID") or os.environ.get("TYPESAFE_BASE_URL"):
        parser.error("benchmark requires native TypeSafe; unset routing overrides")
    example = root / "examples/11-openai-decisions"
    definition = load_definition(example / "ticket.toml")
    cases = [json.loads(line) for line in (example / "cases.jsonl").read_text().splitlines()]
    transports = {p: MeasuredHTTP() for p in PRICES}
    clients = {
        "openai": OpenAIDecisionsClient(model="gpt-6-luna", max_retries=0, timeout=30, http_client=transports["openai"]),
        "typesafe": TypeSafeClient(model="jev-1.13.0", max_retries=0, timeout=30, http_client=transports["typesafe"]),
    }
    report: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(), "pricing_checked_on": "2026-10-07",
        "methodology": {"rounds": args.rounds, "cases": len(cases), "calls_per_provider": args.rounds * len(cases),
                        "concurrency": 1, "local_cache": False, "max_retries": 0, "timeout_seconds": 30,
                        "order": "Alternating provider order per paired request; persistent independent HTTP clients.",
                        "latency": "perf_counter_ns around system_one, including encoding, network, response parsing and validation; first call included.",
                        "percentiles": "Linear interpolation over sorted successful calls.",
                        "location": "User workstation, Europe/Prague timezone; network location not independently verified.",
                        "python": platform.python_version(),
                        "limitations": "Seven short synthetic cases repeated; not 21 independent tasks. Small sample, no throughput or production calibration claim. Unknown labels excluded; three decisions per call. Provider-side caching is not controlled. Costs are list-price estimates from reported input usage, excluding credits, taxes, discounts, regional and long-context premiums."},
        "prices": PRICES, "questions": definition.questions,
        "endpoints": {"openai": clients["openai"].base_url + "/decisions",
                      "typesafe": clients["typesafe"].base_url + "/systemone"},
        "requests": [],
    }
    def save() -> None:
        report["summary"] = {p: summarize(report["requests"], p) for p in clients}
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    save()
    try:
        for round_index in range(args.rounds):
            for case_index, case in enumerate(cases):
                order = ["openai", "typesafe"] if (round_index * len(cases) + case_index) % 2 == 0 else ["typesafe", "openai"]
                for provider in order:
                    row: dict[str, Any] = {"provider": provider, "round": round_index + 1, "case_id": case["id"],
                                           "labels": case["labels"], "state": case["state"]}
                    started = time.perf_counter_ns()
                    try:
                        row["result"] = await clients[provider].system_one(state=case["state"], questions=definition.questions)
                    except Exception as error:
                        row["error"] = {"type": type(error).__name__, "message": str(error)}
                    row["elapsed_ms"] = (time.perf_counter_ns() - started) / 1e6
                    row.update(transports[provider].last)
                    if "result" in row:
                        row["estimated_cost_usd"] = row["result"]["usage"]["input_tokens"] * PRICES[provider]["input_usd_per_million"] / 1e6
                    report["requests"].append(row)
                    save()
                    print(f"{provider} round {round_index + 1} {case['id']}: {row['elapsed_ms']:.1f} ms, {'ok' if 'result' in row else 'failed'}", flush=True)
        report["completed_at"] = datetime.now(UTC).isoformat()
        report["network_calls"] = {p: t.calls for p, t in transports.items()}
        save()
    finally:
        for client in clients.values():
            client.close()
        for transport in transports.values():
            transport.close()
    for provider, summary in report["summary"].items():
        assert summary["successes"] >= 20, f"{provider} has fewer than 20 successful calls"
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
