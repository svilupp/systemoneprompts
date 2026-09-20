"""Validation and native-shape conversion for question declarations."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from .diagnostics import Diagnostic, SourceLocation, diagnostic
from .json_values import is_entry_type, is_plain_object, js_string
from .locate import SourceIndex, locate

QUESTION_TYPES = ("noul", "choice", "score")
QUESTION_FIELDS = {"type", "instructions", "criteria"}
MAX_CHOICE_LABELS = 255
_BACKTICK_RE = re.compile(r"`([^`]+)`")


def question_infos(questions: Mapping[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    infos: dict[str, dict[str, Any]] = {}
    for question_id, question in questions.items():
        info: dict[str, Any] = {"id": question_id, "type": question.get("type")}
        if question.get("type") == "choice" and isinstance(question.get("criteria"), dict):
            info["choice_labels"] = list(question["criteria"])
        infos[question_id] = info
    return infos


def validate_questions(
    raw: Any, index: SourceIndex
) -> tuple[dict[str, dict[str, Any]], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    questions: dict[str, dict[str, Any]] = {}
    table_location = locate(index, table="questions")
    if raw is None or (is_plain_object(raw) and not raw):
        diagnostics.append(
            diagnostic(
                "error",
                "questions-empty",
                "[questions] must contain at least one question",
                table_location,
            )
        )
        return questions, diagnostics
    if not is_plain_object(raw):
        diagnostics.append(
            diagnostic(
                "error",
                "questions-not-table",
                "[questions] must be a table of question objects",
                table_location,
            )
        )
        return questions, diagnostics

    for question_id, value in raw.items():
        location = locate(
            index, table=f"questions.{question_id}", section="questions", key=question_id
        )
        question, item_diagnostics = _validate_question(str(question_id), value, location)
        diagnostics.extend(item_diagnostics)
        if question is not None:
            questions[str(question_id)] = question
    return questions, diagnostics


def _validate_question(
    question_id: str, value: Any, location: SourceLocation
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    if not is_plain_object(value):
        return None, [
            diagnostic(
                "error", "question-not-table", f"question `{question_id}` must be a table", location
            )
        ]

    extras = [key for key in value if key not in QUESTION_FIELDS]
    for key in extras:
        diagnostics.append(
            diagnostic(
                "error",
                "unknown-question-field",
                f"question `{question_id}` has unknown field `{key}`",
                location,
                "only `type`, `instructions`, and `criteria` are allowed",
            )
        )

    question_type = value.get("type")
    if question_type not in QUESTION_TYPES:
        diagnostics.append(
            diagnostic(
                "error",
                "invalid-question-type",
                f"question `{question_id}` has {'missing' if question_type is None else 'invalid'} type"
                + ("" if question_type is None else f" `{js_string(question_type)}`"),
                location,
                'type must be "noul", "choice", or "score"',
            )
        )
        return None, diagnostics

    if "instructions" in value and not is_entry_type(value["instructions"]):
        diagnostics.append(
            diagnostic(
                "error",
                "invalid-instructions",
                f"question `{question_id}` instructions must be a string, table, or array",
                location,
            )
        )
        return None, diagnostics

    if question_type == "noul":
        question, extra = _validate_noul(question_id, value, location, diagnostics)
    elif question_type == "choice":
        question, extra = _validate_choice(question_id, value, location, diagnostics)
    else:
        question, extra = _validate_score(question_id, value, location, diagnostics)
    diagnostics.extend(extra)
    return question, diagnostics


def _validate_noul(
    question_id: str,
    value: dict[str, Any],
    location: SourceLocation,
    diagnostics: list[Diagnostic],
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    extra: list[Diagnostic] = []
    criteria = value.get("criteria")
    if criteria is not None:
        if not is_plain_object(criteria):
            extra.append(
                diagnostic(
                    "error",
                    "noul-criteria",
                    f"Noul `{question_id}` criteria must be a table with optional true/false keys",
                    location,
                )
            )
            return None, extra
        unknown = [key for key in criteria if key not in {"true", "false"}]
        if unknown:
            extra.append(
                diagnostic(
                    "error",
                    "noul-criteria-keys",
                    f"Noul `{question_id}` criteria may only contain true/false; found "
                    + ", ".join(f"`{key}`" for key in unknown),
                    location,
                )
            )
            return None, extra
        for key in ("true", "false"):
            if key in criteria and not is_entry_type(criteria[key]):
                extra.append(
                    diagnostic(
                        "error",
                        "noul-criteria-entry",
                        f"Noul `{question_id}` criteria.{key} must be a string, table, or array",
                        location,
                    )
                )
                return None, extra
    return _question_object(question_type="noul", value=value, criteria=criteria), extra


def _validate_choice(
    question_id: str,
    value: dict[str, Any],
    location: SourceLocation,
    diagnostics: list[Diagnostic],
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    extra: list[Diagnostic] = []
    criteria = value.get("criteria")
    if type(criteria) is not dict:
        extra.append(
            diagnostic(
                "error",
                "choice-criteria",
                f"Choice `{question_id}` requires a non-empty criteria table",
                location,
            )
        )
        return None, extra
    labels = list(criteria)
    if not labels:
        extra.append(
            diagnostic(
                "error",
                "choice-criteria-empty",
                f"Choice `{question_id}` criteria must not be empty",
                location,
            )
        )
        return None, extra
    if len(labels) > MAX_CHOICE_LABELS:
        extra.append(
            diagnostic(
                "error",
                "choice-criteria-limit",
                f"Choice `{question_id}` has {len(labels)} labels; maximum is {MAX_CHOICE_LABELS}",
                location,
            )
        )
        return None, extra
    for label, entry in criteria.items():
        if not is_entry_type(entry):
            extra.append(
                diagnostic(
                    "error",
                    "choice-criteria-entry",
                    f"Choice `{question_id}` criteria.{label} must be a string, table, or array",
                    location,
                )
            )
            return None, extra
    return _question_object("choice", value, criteria), extra


def _validate_score(
    question_id: str,
    value: dict[str, Any],
    location: SourceLocation,
    diagnostics: list[Diagnostic],
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    extra: list[Diagnostic] = []
    criteria = value.get("criteria")
    if type(criteria) is not list:
        extra.append(
            diagnostic(
                "error",
                "score-criteria",
                f"Score `{question_id}` requires criteria as an array of at least 2 entries",
                location,
            )
        )
        return None, extra
    if len(criteria) < 2:
        extra.append(
            diagnostic(
                "error",
                "score-criteria-min",
                f"Score `{question_id}` criteria must have at least 2 entries",
                location,
            )
        )
        return None, extra
    for index, entry in enumerate(criteria):
        if not is_entry_type(entry):
            extra.append(
                diagnostic(
                    "error",
                    "score-criteria-entry",
                    f"Score `{question_id}` criteria[{index}] must be a string, table, or array",
                    location,
                )
            )
            return None, extra
    return _question_object("score", value, criteria), extra


def _question_object(question_type: str, value: dict[str, Any], criteria: Any) -> dict[str, Any]:
    question: dict[str, Any] = {"type": question_type}
    if "instructions" in value:
        question["instructions"] = value["instructions"]
    if criteria is not None or question_type != "noul":
        if "criteria" in value:
            question["criteria"] = criteria
    return question


def collect_backticks(*values: Any) -> list[str]:
    found: list[str] = []

    def collect(text: str) -> None:
        for match in _BACKTICK_RE.finditer(text):
            token = match.group(1)
            if token and token not in found:
                found.append(token)

    for value in values:
        _walk_strings(value, collect)
    return found


def _walk_strings(value: Any, callback: Callable[[str], None]) -> None:
    if isinstance(value, str):
        callback(value)
    elif type(value) is list:
        for item in value:
            _walk_strings(item, callback)
    elif is_plain_object(value):
        for item in value.values():
            _walk_strings(item, callback)


def lint_backticks(
    questions: dict[str, dict[str, Any]],
    requirements: Mapping[str, str],
    index: SourceIndex,
) -> list[Diagnostic]:
    from .diagnostics import nearest_match
    from .requirements import PathSegment, format_path, parse_path, path_guarantees_token

    guaranteed: list[tuple[str, list[PathSegment] | None]] = []
    for path in requirements:
        segments = parse_path(path)
        guaranteed.append((format_path(segments) if segments is not None else path, segments))
    guaranteed_paths = [formatted for formatted, _ in guaranteed]
    diagnostics: list[Diagnostic] = []
    for question_id, question in questions.items():
        location = locate(
            index, table=["questions", question_id], section="questions", key=question_id
        )
        for token in collect_backticks(question.get("instructions"), question.get("criteria")):
            segments = parse_path(token)
            if segments is None:
                continue
            if any(
                required is not None and path_guarantees_token(required, segments)
                for _, required in guaranteed
            ):
                continue
            suggestion = nearest_match(token, guaranteed_paths)
            diagnostics.append(
                diagnostic(
                    "warning",
                    "unguaranteed-backtick",
                    f"`{token}` is not guaranteed by [requires]",
                    location,
                    f"did you mean `{suggestion}`?" if suggestion else None,
                )
            )
    return diagnostics


__all__ = [
    "MAX_CHOICE_LABELS",
    "QUESTION_TYPES",
    "collect_backticks",
    "lint_backticks",
    "question_infos",
    "validate_questions",
]
