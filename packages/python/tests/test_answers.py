from __future__ import annotations

import math

import systemoneprompts as sop
from systemoneprompts import (
    choice_label,
    is_answer_for_question,
    is_answer_shape,
    noul_value,
    partition_answers,
    score_value,
    wire_questions,
)

noul_question = {"type": "noul", "instructions": "Urgent?"}
noul_answer = {"type": "noul", "noul": 0.8}
choice_question = {
    "type": "choice",
    "instructions": "Which?",
    "criteria": {"billing": "Billing", "orders": "Orders"},
}
choice_answer = {
    "type": "choice",
    "choice": "billing",
    "confidence": 0.9,
    "probabilities": {"billing": 0.8, "orders": 0.2},
}
score_question = {
    "type": "score",
    "instructions": "How angry?",
    "criteria": ["Calm", "Civil", "Angry"],
}
score_answer = {
    "type": "score",
    "score": 1.2,
    "confidence": 0.7,
    "legend": {"0": "Calm", "1": "Civil", "2": "Angry"},
    "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3},
}


def test_valid_noul_choice_and_score_answers() -> None:
    assert is_answer_shape(noul_answer)
    assert is_answer_for_question(noul_question, noul_answer)
    assert noul_value(noul_answer) == 0.8
    assert choice_label(noul_answer) is None
    assert score_value(noul_answer) is None

    assert is_answer_shape(choice_answer)
    assert is_answer_for_question(choice_question, choice_answer)
    assert choice_label(choice_answer) == "billing"
    assert noul_value(choice_answer) is None

    assert is_answer_shape(score_answer)
    assert is_answer_for_question(score_question, score_answer)
    assert score_value(score_answer) == 1.2
    assert choice_label(score_answer) is None


def test_malformed_answers_fail_shape_or_question_checks() -> None:
    assert not is_answer_shape({"type": "noul", "noul": math.inf})
    assert not is_answer_shape({"type": "noul", "noul": True})
    assert not is_answer_for_question(noul_question, {"type": "choice", "choice": "billing"})
    assert not is_answer_for_question(
        choice_question,
        {
            "type": "choice",
            "choice": "billing",
            "confidence": 0.9,
            "probabilities": {"billing": 1},
        },
    )
    assert not is_answer_for_question(
        score_question,
        {
            "type": "score",
            "score": 1,
            "confidence": 1,
            "legend": {"0": "Calm", "1": "Civil"},
            "probabilities": {"0": 1, "1": 0, "2": 0},
        },
    )
    assert noul_value({"type": "noul"}) is None
    assert choice_label({"type": "choice", "choice": "billing", "confidence": 1}) is None
    assert score_value({"type": "score", "score": 1, "confidence": 1, "legend": {}}) is None


def test_wire_questions_keeps_type_instructions_criteria_and_drops_extra_keys() -> None:
    wired = wire_questions(
        {
            "b": {"type": "noul", "extra": True, "hash": "x"},
            "a": {"type": "noul", "instructions": "A?", "extra": 1},
            "c": {"type": "choice", "criteria": {"yes": "Yes"}, "extra": None},
        }
    )
    assert list(wired) == ["b", "a", "c"]
    assert wired == {
        "b": {"type": "noul"},
        "a": {"type": "noul", "instructions": "A?"},
        "c": {"type": "choice", "criteria": {"yes": "Yes"}},
    }


def test_partition_answers_splits_missing_malformed_and_valid_ids() -> None:
    questions = {"missing": noul_question, "bad": choice_question, "ok": noul_question}
    assert partition_answers(questions, None) == {
        "valid": {},
        "missing": ["missing", "bad", "ok"],
        "malformed": [],
    }
    assert partition_answers(questions, {"bad": noul_answer, "ok": noul_answer}) == {
        "valid": {"ok": noul_answer},
        "missing": ["missing"],
        "malformed": ["bad"],
    }


def test_score_value_is_the_expected_value_and_score_level_is_not_exported() -> None:
    assert score_value(score_answer) == 1.2
    assert not hasattr(sop, "score_level")
    assert not hasattr(sop, "scoreLevel")
