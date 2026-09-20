"""Pure evaluation metrics, sweeps, and case execution. Keep out of the core import path."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .definition import Definition
from .diagnostics import SystemOnePromptsError, diagnostic
from .factors import COMPARATOR_KEYS, NOUL_CUTOFF, create_factor_evaluator
from .json_values import is_json_value, is_plain_object, js_string, parse_json
from .requirements import create_state_assert


class EvalCaseError(SystemOnePromptsError):
    """Invalid JSONL cases. `summary` mirrors the TypeScript CLI wording for each stage:
    `N invalid eval case error(s)` for parse/shape errors, `N invalid eval case(s)` for
    `[requires]` failures found during preflight."""

    def __init__(self, messages: Sequence[str], *, stage: str = "parse"):
        noun = "invalid eval case error(s)" if stage == "parse" else "invalid eval case(s)"
        self.summary = f"{len(messages)} {noun}"
        super().__init__(diagnostic("error", "eval-cases", self.summary))
        self.messages = list(messages)


def js_round(value: float) -> int:
    """JavaScript `Math.round`: halves round toward +∞."""
    return int(math.floor(value + 0.5))


def load_eval_cases(text: str, source: str, definition: Definition) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parsed = parse_json(line)
        except json.JSONDecodeError as error:
            errors.append(f"{source}:{index}: {error}")
            continue
        messages = validate_case(parsed, definition)
        if messages:
            errors.extend(f"{source}:{index}: {message}" for message in messages)
            continue
        cases.append(parsed)
    if errors:
        raise EvalCaseError(errors)
    return cases


def validate_case(value: Any, definition: Definition) -> list[str]:
    if not is_plain_object(value):
        return ["each case must be an object"]
    errors: list[str] = []
    if "id" in value and not isinstance(value["id"], str):
        errors.append("`id` must be a string")
    if "state" not in value:
        errors.append("each case needs a `state` field")
    elif not _is_eval_state(value["state"]):
        errors.append("`state` must be null, a string, object, or array")
    if "labels" in value:
        labels = value["labels"]
        if not is_plain_object(labels):
            errors.append("`labels` must be an object")
        else:
            for question_id, expected in labels.items():
                if question_id not in definition.questions:
                    errors.append(f"labels.{question_id}: unknown question id")
                    continue
                question = definition.questions[question_id]
                question_type = question.get("type")
                if question_type == "choice":
                    criteria = question.get("criteria")
                    if not isinstance(expected, str):
                        errors.append(f"labels.{question_id}: expected a Choice label string")
                    elif not isinstance(criteria, dict) or expected not in criteria:
                        errors.append(f"labels.{question_id}: unknown Choice label `{expected}`")
                elif question_type == "noul":
                    if type(expected) is not bool:
                        errors.append(f"labels.{question_id}: expected a Noul boolean")
                elif not _is_score_label(expected, question):
                    length = len(question.get("criteria") or [])
                    errors.append(
                        f"labels.{question_id}: expected a Score integer from 0 through {max(length - 1, 0)}"
                    )
    if "factors" in value:
        factors = value["factors"]
        if not is_plain_object(factors):
            errors.append("`factors` must be an object")
        else:
            for factor_id, expected in factors.items():
                if factor_id not in definition.factor_definitions:
                    errors.append(f"factors.{factor_id}: unknown factor id")
                elif type(expected) is not bool:
                    errors.append(f"factors.{factor_id}: expected a boolean")
    return errors


def _is_eval_state(value: Any) -> bool:
    return is_json_value(value) and (
        value is None or isinstance(value, str) or is_plain_object(value) or type(value) is list
    )


def _is_score_label(expected: Any, question: Mapping[str, Any]) -> bool:
    if type(expected) is int:
        value = expected
    elif type(expected) is float and expected.is_integer():
        value = int(expected)
    else:
        return False
    length = len(question.get("criteria") or [])
    return 0 <= value < length


def _js_string(value: Any) -> str:
    """JavaScript `String(value)` for eval confusion keys and label comparison."""
    return js_string(value)


def prepare_sweep(factor_id: str, definition: Definition) -> dict[str, Any]:
    if factor_id not in definition.factor_definitions:
        raise SystemOnePromptsError(diagnostic("error", "eval-sweep", f"--sweep: unknown factor `{factor_id}`"))
    table = definition.factor_definitions[factor_id]
    if not isinstance(table.get("ref"), str):
        raise SystemOnePromptsError(
            diagnostic(
                "error",
                "eval-sweep",
                f"--sweep: factor `{factor_id}` is not a predicate; only predicates can be swept",
            )
        )
    field = next(
        (name for name in ("noul", "score", "confidence") if is_plain_object(table.get(name))),
        None,
    )
    if field is None:
        raise SystemOnePromptsError(
            diagnostic(
                "error",
                "eval-sweep",
                f"--sweep: factor `{factor_id}` has no numeric comparator to sweep",
            )
        )
    comparator = table[field]
    keys = [key for key in COMPARATOR_KEYS if key in comparator]
    if len(keys) != 1:
        raise SystemOnePromptsError(
            diagnostic(
                "error",
                "eval-sweep",
                f"--sweep: factor `{factor_id}` comparator must have exactly one operator to sweep",
            )
        )
    question = definition.questions.get(table["ref"])
    if field == "score" and question and question.get("type") == "score":
        thresholds = _range(0, len(question["criteria"]) - 1, 0.1)
    else:
        thresholds = _range(0.05, 0.95, 0.05)
    return {
        "id": factor_id,
        "ref": table["ref"],
        "field": field,
        "key": keys[0],
        "table": table,
        "thresholds": thresholds,
    }


def label_of(answer: Any) -> str | None:
    if not is_plain_object(answer):
        return None
    if answer.get("type") == "choice":
        choice = answer.get("choice")
        if isinstance(choice, str):
            return choice
    if answer.get("type") == "noul" and type(answer.get("noul")) in {int, float}:
        return "true" if float(answer["noul"]) >= NOUL_CUTOFF else "false"
    if answer.get("type") == "score" and type(answer.get("score")) in {int, float}:
        return str(js_round(float(answer["score"])))
    return None


def record_near(question_id: str, answer: Any, dest: dict[str, int]) -> None:
    if not is_plain_object(answer):
        return
    if type(answer.get("noul")) in {int, float} and abs(float(answer["noul"]) - NOUL_CUTOFF) <= 0.1:
        dest[question_id] = dest.get(question_id, 0) + 1
    if type(answer.get("confidence")) in {int, float}:
        confidence = float(answer["confidence"])
        if 0.4 <= confidence < 0.75:
            key = f"{question_id}.confidence"
            dest[key] = dest.get(key, 0) + 1


def with_accuracy(tally: Mapping[str, int]) -> dict[str, Any]:
    total = tally.get("total", 0)
    correct = tally.get("correct", 0)
    return {"accuracy": 0 if total == 0 else correct / total, "correct": correct, "total": total}


def ground_truth(
    factor_id: str, ref: str, field: str, key: str, test_case: Mapping[str, Any]
) -> bool | None:
    factors = test_case.get("factors")
    expected = factors.get(factor_id) if isinstance(factors, dict) else None
    if type(expected) is bool:
        return expected
    labels = test_case.get("labels")
    label = labels.get(ref) if isinstance(labels, dict) else None
    if field == "noul" and type(label) is bool:
        return (not label) if key in {"lt", "lte"} else label
    return None


def sweep_factor(sweep: Mapping[str, Any], predictions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    for threshold in sweep["thresholds"]:
        swept = {**sweep["table"], sweep["field"]: {sweep["key"]: threshold}}
        evaluate = create_factor_evaluator({sweep["id"]: swept})
        correct = 0
        total = 0
        for prediction in predictions:
            want = ground_truth(
                sweep["id"], sweep["ref"], sweep["field"], sweep["key"], prediction["test_case"]
            )
            if want is None:
                continue
            predicted = evaluate(prediction["answers"])[sweep["id"]]
            total += 1
            if predicted == want:
                correct += 1
        rows.append({"threshold": threshold, **with_accuracy({"correct": correct, "total": total})})
    return {
        "factor": sweep["id"],
        "ref": sweep["ref"],
        "field": sweep["field"],
        "comparator": sweep["key"],
        "rows": rows,
    }


def _range(start: float, stop: float, step: float) -> list[float]:
    values: list[float] = []
    current = start
    while current <= stop + 1e-9:
        values.append(float(f"{current:.2f}"))
        current += step
    return values


def protect_report_path(report: str, *inputs: str) -> None:
    resolved_report = Path(report).resolve()
    for path in inputs:
        if Path(path).resolve() == resolved_report:
            raise SystemOnePromptsError(
                diagnostic(
                    "error",
                    "eval-report",
                    "--report must not overwrite the definition or cases input",
                )
            )


def preflight_eval(
    definition: Definition,
    cases: Sequence[Mapping[str, Any]],
    sweep: Mapping[str, Any] | None = None,
) -> None:
    """Validate eval cases and sweep truth samples before any provider call."""
    assert_state = create_state_assert(definition.requires)
    state_errors: list[str] = []
    for index, test_case in enumerate(cases):
        try:
            assert_state(test_case["state"])
        except Exception as error:
            case_id = test_case.get("id", str(index))
            state_errors.append(f"case {case_id}: {error}")
    if state_errors:
        raise EvalCaseError(state_errors, stage="state")
    if sweep and not any(
        ground_truth(sweep["id"], sweep["ref"], sweep["field"], sweep["key"], test_case) is not None
        for test_case in cases
    ):
        raise SystemOnePromptsError(
            diagnostic(
                "error",
                "eval-sweep",
                f"--sweep: no usable truth samples for factor `{sweep['id']}`",
            )
        )


def _cache_payload(stats: Any) -> Any:
    if stats is None:
        return None
    if hasattr(stats, "requests"):
        return {
            "requests": stats.requests,
            "hits": stats.hits,
            "misses": stats.misses,
            "keys": list(getattr(stats, "keys", [])),
        }
    return stats


async def execute_eval(
    definition: Definition,
    cases: Sequence[Mapping[str, Any]],
    client: Any,
    *,
    model: str,
    sweep: Mapping[str, Any] | None = None,
    cache_stats: Callable[[], Any] | None = None,
    file: str = "definition.toml",
) -> dict[str, Any]:
    preflight_eval(definition, cases, sweep)
    evaluate = create_factor_evaluator(definition.factor_definitions)

    question_stats: dict[str, dict[str, Any]] = {}
    factor_stats: dict[str, dict[str, int]] = {}
    near_threshold: dict[str, int] = {}
    predictions: list[dict[str, Any]] = []
    errors = 0
    stderr: list[str] = []
    for index, test_case in enumerate(cases):
        case_id = str(test_case.get("id", index))
        try:
            response = await client.system_one(
                state=test_case["state"], questions=definition.questions, model=model
            )
            answers = dict(response.get("answers") or {})
            for question_id, expected in (test_case.get("labels") or {}).items():
                stats = question_stats.setdefault(
                    question_id, {"correct": 0, "total": 0, "confusion": {}}
                )
                stats["total"] += 1
                predicted = label_of(answers.get(question_id)) or "<none>"
                expected_label = _js_string(expected)
                if predicted == expected_label:
                    stats["correct"] += 1
                row = stats["confusion"].setdefault(expected_label, {})
                row[predicted] = row.get(predicted, 0) + 1
                record_near(question_id, answers.get(question_id), near_threshold)
            try:
                factors = evaluate(answers)
            except Exception as error:
                errors += 1
                stderr.append(f"case {case_id}: factor evaluation failed: {error}")
                continue
            predictions.append(
                {"id": case_id, "answers": answers, "factors": factors, "test_case": test_case}
            )
            for factor_id, expected in (test_case.get("factors") or {}).items():
                stats = factor_stats.setdefault(factor_id, {"correct": 0, "total": 0})
                stats["total"] += 1
                if factors.get(factor_id) is expected:
                    stats["correct"] += 1
        except Exception as error:
            errors += 1
            stderr.append(f"case {case_id}: {error}")

    report: dict[str, Any] = {
        "file": file,
        "model": model,
        "cases": len(cases),
        "errors": errors,
        "questions": {
            question_id: {**with_accuracy(stats), "confusion": stats["confusion"]}
            for question_id, stats in question_stats.items()
        },
        "factors": {factor_id: with_accuracy(stats) for factor_id, stats in factor_stats.items()},
        "near_threshold": near_threshold,
    }
    if cache_stats:
        # `JSON.stringify` omits `cache` entirely when no cache is active.
        report["cache"] = _cache_payload(cache_stats())
    report["_stderr"] = stderr
    if sweep:
        report["sweep"] = sweep_factor(sweep, predictions)
    return report


__all__ = [
    "EvalCaseError",
    "execute_eval",
    "js_round",
    "label_of",
    "load_eval_cases",
    "preflight_eval",
    "prepare_sweep",
    "protect_report_path",
    "sweep_factor",
    "validate_case",
]
