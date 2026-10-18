"""Answer JSON shape checks and small accessors."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .json_values import is_json_value, is_plain_object


def is_answer_for_question(question: Any, answer: Any) -> bool:
    if not is_plain_object(question) or not is_answer_shape(answer):
        return False
    if question.get("type") != answer.get("type"):
        return False
    if question.get("type") == "choice":
        criteria = question.get("criteria")
        if not is_plain_object(criteria) or not isinstance(answer.get("choice"), str):
            return False
        if answer["choice"] not in criteria:
            return False
        probabilities = answer.get("probabilities")
        if not is_plain_object(probabilities):
            return False
        return all(
            label in probabilities and _is_finite_number(probabilities[label]) for label in criteria
        )
    if question.get("type") == "score":
        criteria = question.get("criteria")
        if type(criteria) is not list:
            return False
        legend = answer.get("legend")
        probabilities = answer.get("probabilities")
        if not is_plain_object(legend) or not is_plain_object(probabilities):
            return False
        return all(
            str(index) in legend
            and str(index) in probabilities
            and _is_finite_number(probabilities[str(index)])
            for index in range(len(criteria))
        )
    return True


def is_answer_shape(answer: Any) -> bool:
    if not is_plain_object(answer) or not is_json_value(answer):
        return False
    answer_type = answer.get("type")
    if answer_type == "box":
        return (
            "box" in answer
            and is_box_coordinates(answer["box"])
            and "confidence" in answer
            and (
                answer["confidence"] is None
                or (_is_finite_number(answer["confidence"]) and 0 <= answer["confidence"] <= 1)
            )
        )
    if answer_type == "noul":
        return _is_finite_number(answer.get("noul"))
    if answer_type == "choice":
        return (
            isinstance(answer.get("choice"), str)
            and _is_finite_number(answer.get("confidence"))
            and is_plain_object(answer.get("probabilities"))
        )
    if answer_type == "score":
        return (
            _is_finite_number(answer.get("score"))
            and _is_finite_number(answer.get("confidence"))
            and is_plain_object(answer.get("legend"))
            and is_plain_object(answer.get("probabilities"))
        )
    return False


def noul_value(answer: Any) -> float | int | None:
    if not is_answer_shape(answer) or answer.get("type") != "noul":
        return None
    value = answer.get("noul")
    return value if _is_finite_number(value) else None


def choice_label(answer: Any) -> str | None:
    if not is_answer_shape(answer) or answer.get("type") != "choice":
        return None
    label = answer.get("choice")
    return label if isinstance(label, str) else None


def score_value(answer: Any) -> float | int | None:
    if not is_answer_shape(answer) or answer.get("type") != "score":
        return None
    value = answer.get("score")
    return value if _is_finite_number(value) else None


def wire_questions(questions: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    wired: dict[str, dict[str, Any]] = {}
    for question_id, question in questions.items():
        entry: dict[str, Any] = {"type": question["type"]}
        if "instructions" in question:
            entry["instructions"] = question["instructions"]
        if "criteria" in question:
            entry["criteria"] = question["criteria"]
        wired[question_id] = entry
    return wired


def partition_answers(questions: Mapping[str, Any], answers: Any) -> dict[str, Any]:
    valid: dict[str, Any] = {}
    missing: list[str] = []
    malformed: list[str] = []
    answers_object = answers if is_plain_object(answers) else None
    for question_id, question in questions.items():
        if answers_object is None or question_id not in answers_object:
            missing.append(question_id)
        elif not is_answer_for_question(question, answers_object[question_id]):
            malformed.append(question_id)
        else:
            valid[question_id] = answers_object[question_id]
    return {"valid": valid, "missing": missing, "malformed": malformed}


def _is_finite_number(value: Any) -> bool:
    if type(value) is not int and type(value) is not float:
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


__all__ = [
    "choice_label",
    "is_answer_for_question",
    "is_answer_shape",
    "noul_value",
    "partition_answers",
    "score_value",
    "wire_questions",
]


def is_box_coordinates(value: Any) -> bool:
    return (
        is_plain_object(value)
        and set(value) == {"top", "bottom", "left", "right"}
        and all(
            _is_finite_number(value.get(key)) and 0 <= value[key] <= 1
            for key in ("top", "bottom", "left", "right")
        )
        and value["top"] < value["bottom"]
        and value["left"] < value["right"]
    )


def box_coordinates(answer: Any) -> dict[str, Any] | None:
    return answer["box"] if is_answer_shape(answer) and answer.get("type") == "box" else None


def is_vision_response(value: Any, questions: Mapping[str, Any] | None = None) -> bool:
    """Validate a complete native image/Box response before caching or normalization."""
    if (
        not is_plain_object(value)
        or not isinstance(value.get("model"), str)
        or not value["model"].strip()
        or not is_plain_object(value.get("answers"))
        or not is_plain_object(value.get("usage"))
    ):
        return False
    if not all(
        _is_finite_number(value["usage"].get(key))
        and value["usage"][key] >= 0
        and value["usage"][key] % 1 == 0
        for key in ("input_tokens", "output_tokens")
    ):
        return False
    answers = value["answers"]
    if questions is None:
        return all(is_answer_shape(answer) for answer in answers.values())
    return set(answers) == set(questions) and all(
        is_answer_for_question(question, answers[ref]) for ref, question in questions.items()
    )
