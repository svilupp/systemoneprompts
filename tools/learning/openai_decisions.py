"""Explicit, synthetic learning probes. No production client or SDK dependency.

Run from either package with its scripts/run-quiet.sh wrapper; see PLAN.md.
Offline by default. --live sends at most 13 requests, without retries.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = "gpt-6-luna"


def text(value: object) -> str:
    return (
        value
        if isinstance(value, str)
        else json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def encode(state: object, questions: dict) -> tuple[dict, dict]:
    """Candidate translation; intentionally private to this experiment."""
    names, wire = {}, []
    for index, (qid, question) in enumerate(questions.items()):
        name = f"q{index}"
        names[name] = qid
        instructions = question.get("instructions")
        entry = {
            "name": name,
            "instructions": text(instructions)
            if instructions is not None
            else "Evaluate the supplied evidence against the criteria.",
        }
        criteria = question.get("criteria")
        if question["type"] == "noul":
            entry["type"] = "predicate"
            if criteria:
                entry["instructions"] += "\nOutcome criteria (JSON): " + text(criteria)
        elif question["type"] == "choice":
            entry.update(
                type="choice",
                choices=[
                    {
                        "value": label,
                        **({"description": text(description)} if description is not None else {}),
                    }
                    for label, description in criteria.items()
                ],
            )
        else:
            entry.update(
                type="score",
                levels=[
                    {
                        "label": str(index),
                        **({"description": text(description)} if description is not None else {}),
                    }
                    for index, description in enumerate(criteria)
                ],
            )
        wire.append(entry)
    return {"model": MODEL, "input": text(state), "questions": wire}, names


def probability(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def normalize(raw: dict, questions: dict, names: dict) -> dict:
    """Strict candidate normalization, including refusal and malformed failures."""
    answers = {}
    for answer in raw["answers"]:
        name = answer.get("name")
        if name not in names or names[name] in answers:
            raise ValueError("unexpected or duplicate answer name")
        qid = names[name]
        question = questions[qid]
        kind = question["type"]
        if answer["type"] == "refusal":
            raise ValueError(f"refusal for {qid}")
        if answer["type"] != ("predicate" if kind == "noul" else kind):
            raise ValueError("answer type mismatch")
        if kind == "noul":
            if not probability(answer["probability"]):
                raise ValueError("invalid probability")
            answers[qid] = {"type": "noul", "noul": answer["probability"]}
            continue
        if not probability(answer["confidence"]):
            raise ValueError("invalid confidence")
        criteria = question["criteria"]
        expected = set(criteria) if kind == "choice" else {str(i) for i in range(len(criteria))}
        probs = {}
        for item in answer["probabilities"]:
            value = item["value"]
            if kind == "score" and type(value) is not int:
                raise ValueError("noninteger score index")
            if kind == "choice" and not isinstance(value, str):
                raise ValueError("nonstring choice")
            key = str(value)
            if key not in expected or key in probs or not probability(item["probability"]):
                raise ValueError("invalid distribution entry")
            probs[key] = item["probability"]
        if set(probs) != expected or abs(sum(probs.values()) - 1) > 0.02:
            raise ValueError("incomplete or unnormalized distribution")
        normalized = {
            "type": kind,
            "confidence": answer["confidence"],
            "probabilities": probs,
        }
        if kind == "choice":
            if answer["choice"] not in expected:
                raise ValueError("unknown choice")
            normalized["choice"] = answer["choice"]
        else:
            score = answer["score"]
            if (
                type(score) not in (int, float)
                or not math.isfinite(score)
                or not 0 <= score <= len(criteria) - 1
            ):
                raise ValueError("invalid score")
            normalized.update(score=score, legend={str(i): v for i, v in enumerate(criteria)})
        answers[qid] = normalized
    if set(answers) != set(questions):
        raise ValueError("missing answers")
    return {
        "model": raw["model"],
        "answers": answers,
        "usage": {
            "input_tokens": raw["usage"]["input_tokens"],
            "output_tokens": raw["usage"]["output_tokens"],
        },
    }


QUESTIONS = {
    "charged.twice": {
        "type": "noul",
        "instructions": "Was the customer charged twice?",
        "criteria": {"true": "Two charges for one order", "false": "Only one charge"},
    },
    "__proto__": {
        "type": "choice",
        "instructions": "Which department handles this?",
        "criteria": {
            "billing": "Payments and refunds",
            "shipping": "Delivery and tracking",
        },
    },
    "severity": {
        "type": "score",
        "instructions": "Rate issue severity.",
        "criteria": [
            "No issue",
            {"issue": "Payment requires correction"},
            "Permanent account loss",
        ],
    },
}


def offline() -> int:
    payload, names = encode({"ticket": "Charged twice"}, QUESTIONS)
    assert payload["input"] == '{"ticket":"Charged twice"}'
    assert list(names.values()) == list(QUESTIONS)
    assert all(isinstance(q["instructions"], str) for q in payload["questions"])
    raw = {
        "model": MODEL,
        "usage": {"input_tokens": 10, "output_tokens": 0},
        "answers": [
            {"type": "predicate", "name": "q0", "probability": 0.8},
            {
                "type": "choice",
                "name": "q1",
                "choice": "billing",
                "confidence": 0.9,
                "probabilities": [
                    {"value": "billing", "probability": 0.9},
                    {"value": "shipping", "probability": 0.1},
                ],
            },
            {
                "type": "score",
                "name": "q2",
                "score": 1.1,
                "confidence": 0.6,
                "probabilities": [
                    {"value": 0, "probability": 0.1},
                    {"value": 1, "probability": 0.7},
                    {"value": 2, "probability": 0.2},
                ],
            },
        ],
    }
    result = normalize(raw, QUESTIONS, names)
    assert result["answers"]["severity"]["score"] == 1.1
    assert result["answers"]["severity"]["legend"]["1"] == QUESTIONS["severity"]["criteria"][1]
    assert result["answers"]["__proto__"]["choice"] == "billing"
    bad = []
    for mutate in (
        lambda r: r["answers"].pop(),
        lambda r: r["answers"].append(r["answers"][0]),
        lambda r: r["answers"][0].update(type="refusal"),
        lambda r: r["answers"][0].update(probability=1.1),
        lambda r: r["answers"][1]["probabilities"].pop(),
        lambda r: r["answers"][2]["probabilities"][0].update(value=0.5),
    ):
        specimen = json.loads(json.dumps(raw))
        mutate(specimen)
        bad.append(specimen)
    for specimen in bad:
        try:
            normalize(specimen, QUESTIONS, names)
        except ValueError:
            continue
        raise AssertionError("malformed specimen was accepted")
    report_path = ROOT / "tools/learning/openai-decisions-results.json"
    if report_path.exists():
        report = json.loads(report_path.read_text())
        by_name = {case["name"]: case for case in report["cases"]}
        assert len(by_name) == len(probes()), "incomplete recorded learning run"
        for label, _, questions, mapping in probes():
            case = by_name[label]
            assert case["status"] == expected_status(label), case
            if questions is not None:
                assert normalize(case["response"], questions, mapping) == case["normalized"]
        print(
            "Recorded API contract: all 13 expected statuses and both raw-response translations passed"
        )
    print(
        "Offline: encoding, identity, fractional score, original legend, and six failure cases passed"
    )
    return 0


def probes() -> list[tuple[str, dict, dict | None, dict | None]]:
    base, names = encode({"ticket": {"message": "I was charged twice for my order."}}, QUESTIONS)
    cases = [("translated_mixed", base, QUESTIONS, names)]
    predicate = {"type": "predicate", "name": "p", "instructions": "Is the sky blue?"}

    def add(label: str, question: dict, **extra: object) -> None:
        cases.append(
            (
                label,
                {
                    "model": MODEL,
                    "input": "The sky is blue.",
                    "questions": [question],
                    **extra,
                },
                None,
                None,
            )
        )

    add(
        "object_instructions",
        {**predicate, "instructions": {"condition": "sky is blue"}},
    )
    add("missing_instructions", {"type": "predicate", "name": "p"})
    add("predicate_criteria", {**predicate, "criteria": {"true": "Blue"}})
    add("duplicate_names", predicate, questions=[predicate, predicate])
    add("literal_names", {**predicate, "name": "__proto__.a[-1]"})
    add("unsupported_model", predicate, model="jev-latest")
    add(
        "null_description",
        {
            "type": "choice",
            "name": "p",
            "instructions": "Choose a color.",
            "choices": [{"value": "blue", "description": None}, {"value": "red"}],
        },
    )
    add(
        "single_choice",
        {
            "type": "choice",
            "name": "p",
            "instructions": "Choose a color.",
            "choices": [{"value": "blue"}],
        },
    )
    add("empty_questions", predicate, questions=[])
    add(
        "user_message",
        predicate,
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "The sky is blue."}],
            }
        ],
    )
    structured = {
        "nested": {
            "type": "noul",
            "instructions": {"condition": "ticket.message reports duplicate billing"},
            "criteria": {
                "true": ["Two charges", "One order"],
                "false": "No duplicate charge",
            },
        }
    }
    request, mapping = encode(
        {"ticket": {"message": "I was charged twice for my order."}}, structured
    )
    cases.append(("structured_instruction_rendering", request, structured, mapping))
    add(
        "object_description",
        {
            "type": "choice",
            "name": "p",
            "instructions": "Choose a color.",
            "choices": [
                {"value": "blue", "description": {"color": "blue"}},
                {"value": "red"},
            ],
        },
    )
    return cases


def expected_status(label: str) -> int:
    if label in {
        "translated_mixed",
        "literal_names",
        "user_message",
        "structured_instruction_rendering",
    }:
        return 200
    return 404 if label == "unsupported_model" else 400


def live(output: Path) -> int:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("\"'")
    if not key:
        raise SystemExit("OPENAI_API_KEY is required for --live")
    report = {
        "date": datetime.now(UTC).isoformat(),
        "endpoint": "https://api.openai.com/v1/decisions",
        "model": MODEL,
        "cases": [],
    }
    failures = 0
    for label, payload, questions, names in probes():
        request = urllib.request.Request(
            report["endpoint"],
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, body, request_id = (
                    response.status,
                    json.load(response),
                    response.headers.get("x-request-id"),
                )
        except urllib.error.HTTPError as error:
            status, body, request_id = (
                error.code,
                json.loads(error.read()),
                error.headers.get("x-request-id"),
            )
        except (urllib.error.URLError, TimeoutError) as error:
            status, body, request_id = 0, {"error": type(error).__name__}, None
        record = {
            "name": label,
            "request": payload,
            "status": status,
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "request_id": request_id,
            "response": body,
        }
        record["expected_status"] = expected_status(label)
        if status != expected_status(label):
            failures += 1
            record["status_mismatch"] = True
        if questions is not None:
            try:
                assert status == 200, f"HTTP {status}"
                record["normalized"] = normalize(body, questions, names)
            except (AssertionError, ValueError, KeyError, TypeError) as error:
                record["normalization_error"] = str(error)
                failures += 1
        report["cases"].append(record)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2).replace(key, "[REDACTED]") + "\n"
        )
        print(f"{label}: HTTP {status}, {record['elapsed_ms']}ms")
        if status in (401, 403, 429) or status == 0:
            print("Stopping after authentication, access, rate-limit, or network failure")
            return 1
    return int(failures > 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "tools/learning/openai-decisions-results.json",
    )
    args = parser.parse_args()
    raise SystemExit(live(args.output) if args.live else offline())
