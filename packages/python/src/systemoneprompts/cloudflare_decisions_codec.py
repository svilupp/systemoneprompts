"""Jev-compatible Clef request and response validation."""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import quote, urlsplit

from .diagnostics import SystemOnePromptsError, diagnostic
from .json_values import canonical_json, is_json_value
from .locate import index_source
from .questions import validate_questions


class CloudflareDecisionsError(SystemOnePromptsError):
    def __init__(
        self,
        message: str,
        *,
        kind: str,
        body: Any = None,
        status: int | None = None,
        request_id: str | None = None,
        retry_after: float | None = None,
        code: str | None = None,
    ):
        super().__init__(diagnostic("error", code or f"cloudflare-{kind}", message))
        self.kind = kind
        self.body = body
        self.status = status
        self.request_id = request_id
        self.retry_after = retry_after
        self.code = code


def _incompatible(code: str, message: str) -> Any:
    raise CloudflareDecisionsError(message, kind="compatibility", code=code)


def _model(value: Any) -> str:
    if not isinstance(value, str):
        _incompatible("cloudflare-model", "model must be clef or clef-flash")
    model = str(value).strip().removeprefix("@cf/cloudflare/")
    if model not in ("clef", "clef-flash"):
        _incompatible("cloudflare-model", "model must be clef or clef-flash")
    return model


def _normalize_base_url(value: str | None = None, account_id: str = "") -> str:
    normalized = (
        (
            value
            if value is not None
            else "https://api.cloudflare.com/client/v4/accounts/"
            + quote(account_id, safe="")
            + "/ai/run"
        )
        .strip()
        .rstrip("/")
    )
    try:
        parsed = urlsplit(normalized)
        valid = parsed.scheme in ("http", "https") and bool(parsed.hostname)
        valid = valid and parsed.username is None and parsed.password is None
        valid = valid and not parsed.query and not parsed.fragment
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        _incompatible(
            "cloudflare-base-url",
            "base_url must be an HTTP(S) URL without credentials, query, or fragment",
        )
    return normalized


def _encode(state: Any, questions: Any, model: str) -> tuple[dict[str, Any], list[str]]:
    if not is_json_value(state):
        _incompatible("cloudflare-state-json", "state must be JSON-compatible")
    checked, diagnostics = validate_questions(questions, index_source(""))
    errors = [d for d in diagnostics if d.severity == "error"]
    if errors:
        _incompatible(errors[0].code, "; ".join(d.message for d in errors))
    ids = list(questions)
    if len(ids) > 64:
        _incompatible("cloudflare-question-limit", "at most 64 questions are supported")

    def empty(value: Any) -> bool:
        return (
            value is None
            or isinstance(value, str)
            and not value.strip()
            or type(value) in (list, dict)
            and not value
        )

    wire = {}
    for i, identifier in enumerate(ids):
        question = checked[identifier]
        if question["type"] == "choice" and len(question["criteria"]) < 2:
            _incompatible(
                "cloudflare-choice-min-options", f"question {identifier} needs at least two options"
            )
        if question["type"] == "score" and len(question["criteria"]) > 10:
            _incompatible(
                "cloudflare-score-max-levels", f"question {identifier} allows at most ten levels"
            )
        if (
            question["type"] == "noul"
            and empty(question.get("instructions"))
            and all(empty(v) for v in (question.get("criteria") or {}).values())
        ):
            _incompatible(
                "cloudflare-question-empty",
                f"question {identifier} needs instructions or outcome criteria",
            )
        wire[f"q{i}"] = {
            **question,
            "instructions": "Evaluate the supplied evidence against the criteria."
            if empty(question.get("instructions"))
            else question["instructions"],
        }
    return {"model": _model(model), "state": state, "questions": wire}, ids


def _validate_normalized_result(raw: Any, questions: Any) -> dict[str, Any]:
    def invalid() -> Any:
        raise CloudflareDecisionsError(
            "Invalid Cloudflare Decisions response", kind="response", body=raw
        )

    def probability(value: Any) -> bool:
        return type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value)

    if (
        type(raw) is not dict
        or not isinstance(raw.get("model"), str)
        or not raw["model"].strip()
        or type(raw.get("answers")) is not dict
        or type(raw.get("usage")) is not dict
    ):
        invalid()
    if set(raw["answers"]) != set(questions):
        invalid()
    for key in ("input_tokens", "output_tokens"):
        if (
            type(raw["usage"].get(key)) is not int
            or raw["usage"][key] < 0
            or not is_json_value(raw["usage"][key])
        ):
            invalid()
    for identifier, question in questions.items():
        answer = raw["answers"][identifier]
        if type(answer) is not dict or answer.get("type") != question["type"]:
            invalid()
        if question["type"] == "noul":
            if not probability(answer.get("noul")):
                invalid()
            continue
        labels = (
            list(question["criteria"])
            if question["type"] == "choice"
            else [str(i) for i in range(len(question["criteria"]))]
        )
        if (
            not probability(answer.get("confidence"))
            or type(answer.get("probabilities")) is not dict
            or set(answer["probabilities"]) != set(labels)
            or not all(probability(v) for v in answer["probabilities"].values())
        ):
            invalid()
        if question["type"] == "choice":
            if not isinstance(answer.get("choice"), str) or answer["choice"] not in labels:
                invalid()
        else:
            score = answer.get("score")
            if (
                type(score) not in (int, float)
                or not 0 <= score <= len(labels) - 1
                or not math.isfinite(score)
            ):
                invalid()
            legend = {str(i): v for i, v in enumerate(question["criteria"])}
            if not is_json_value(answer.get("legend")) or canonical_json(
                answer.get("legend")
            ) != canonical_json(legend):
                invalid()
    return dict(raw)


def _decode(raw: Any, questions: Any, ids: list[str], request_id: str | None) -> dict[str, Any]:
    result = raw["result"] if type(raw) is dict and type(raw.get("result")) is dict else raw
    wire_questions = {f"q{i}": questions[identifier] for i, identifier in enumerate(ids)}
    try:
        result = _validate_normalized_result(result, wire_questions)
    except CloudflareDecisionsError as error:
        raise CloudflareDecisionsError(
            str(error), kind="response", body=raw, request_id=request_id
        ) from error
    return {
        **result,
        "answers": {identifier: result["answers"][f"q{i}"] for i, identifier in enumerate(ids)},
    }


def _is_valid_decisions_answer(question: Any, answer: Any) -> bool:
    try:
        _validate_normalized_result(
            {
                "model": "cached",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "answers": {"q": answer},
            },
            {"q": question},
        )
        return True
    except (CloudflareDecisionsError, TypeError, ValueError, OverflowError):
        return False
