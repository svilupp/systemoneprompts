from __future__ import annotations

import pytest

from helpers import fixture
from systemoneprompts import (
    SystemOnePromptsError,
    check_definition,
    create_factor_evaluator,
    parse_definition,
)

QUESTIONS = """
[questions.topic]
type = "choice"
instructions = "Which?"
[questions.topic.criteria]
billing = "Charges"
orders = "Shipments"

[questions.refund_requested]
type = "noul"
instructions = "Refund?"

[questions.frustration]
type = "score"
instructions = "How frustrated?"
criteria = ["Calm", "Civil", "Angry"]

[questions.a]
type = "noul"
instructions = "a"

[questions.b]
type = "noul"
instructions = "b"

[questions.c]
type = "noul"
instructions = "c"
"""

ANSWERS = {
    "topic": {
        "type": "choice",
        "choice": "billing",
        "confidence": 0.8,
        "probabilities": {"billing": 0.8, "orders": 0.2},
    },
    "refund_requested": {"type": "noul", "noul": 0.7},
    "frustration": {
        "type": "score",
        "score": 1.6,
        "confidence": 0.72,
        "legend": {"0": "Calm", "1": "Civil", "2": "Angry"},
        "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
    },
    "a": {"type": "noul", "noul": 0.9},
    "b": {"type": "noul", "noul": 0.2},
    "c": {"type": "noul", "noul": 0.6},
}


def factors_of(body: str):
    definition = parse_definition(f"{QUESTIONS}\n[factors]\n{body}\n")
    assert [item for item in check_definition(definition) if item.severity == "error"] == []
    return create_factor_evaluator(definition.factor_definitions)


def test_predicates_match_native_fields() -> None:
    evaluate = factors_of(
        """
"topic.billing" = { ref = "topic", choice = "billing" }
"topic.billing.confident" = { ref = "topic", choice = "billing", confidence = { gte = 0.75 } }
"refund.strong" = { ref = "refund_requested", noul = { gte = 0.7 } }
"spam.gray" = { ref = "refund_requested", noul = { gt = 0.4, lt = 0.6 } }
"high.frustrated" = { ref = "frustration", score = { gte = 1.5 }, confidence = { gte = 0.7 } }
"""
    )
    assert evaluate(ANSWERS) == {
        "topic.billing": True,
        "topic.billing.confident": True,
        "refund.strong": True,
        "spam.gray": False,
        "high.frustrated": True,
    }


def test_bare_noul_cutoff() -> None:
    evaluate = factors_of(
        """
ready = { all = ["a", "c"] }
partial = { any = ["a", "b"] }
blocked = { not = "b" }
"""
    )
    assert evaluate(ANSWERS) == {"ready": True, "partial": True, "blocked": True}
    edge = factors_of('edge = { all = ["a"] }')
    assert edge({"a": {"type": "noul", "noul": 0.5}})["edge"] is True
    assert edge({"a": {"type": "noul", "noul": 0.499}})["edge"] is False


def test_missing_answer_is_an_error_not_false() -> None:
    evaluate = factors_of('ready = { all = ["a"] }')
    with pytest.raises(SystemOnePromptsError, match="missing answer"):
        evaluate({})


def test_nested_factor_is_one_vote() -> None:
    evaluate = factors_of(
        """
inner = { ref = "a", noul = { gte = 0.5 } }
outer = { at_least = 1, of = ["inner", "b"] }
"""
    )
    assert evaluate(ANSWERS)["outer"] is True
    float_count = factors_of(
        """
inner = { ref = "a", noul = { gte = 0.5 } }
outer = { at_least = 1.0, of = ["inner", "b"] }
"""
    )
    assert float_count(ANSWERS)["outer"] is True


def test_cycle_is_reported() -> None:
    definition = parse_definition(fixture("errors/cycle.toml"), filename="cycle.toml")
    codes = [item.code for item in check_definition(definition)]
    assert "cycle" in codes
    assert any("→" in item.message for item in check_definition(definition) if item.code == "cycle")


def test_collision_and_unknown_option() -> None:
    collision = parse_definition(fixture("errors/collision.toml"))
    assert any(item.code == "id-collision" for item in check_definition(collision))
    unknown = parse_definition(fixture("errors/unknown-option.toml"))
    assert any(item.code == "unknown-option" for item in check_definition(unknown))


def test_empty_choice_label_is_a_real_value_check() -> None:
    evaluate = create_factor_evaluator({"f": {"ref": "q", "known": True, "choice": ""}})
    known = {"q": {"type": "choice", "choice": "billing", "confidence": 0.9}}
    assert evaluate(known) == {"f": False}
    assert evaluate({"q": {"type": "choice", "choice": "", "confidence": 0.9}}) == {"f": True}
    strict = create_factor_evaluator({"f": {"ref": "q", "known": False, "choice": ""}})
    with pytest.raises(SystemOnePromptsError, match="missing answer"):
        strict({})


def test_explicit_null_comparators_are_rejected_like_typescript() -> None:
    with pytest.raises(SystemOnePromptsError) as table:
        create_factor_evaluator({"f": {"ref": "q", "known": True, "noul": None}})
    assert table.value.diagnostics[0].code == "comparator-table"
    with pytest.raises(SystemOnePromptsError) as number:
        create_factor_evaluator({"f": {"ref": "q", "noul": {"gte": None, "gt": 0.1}}})
    assert number.value.diagnostics[0].code == "comparator-number"


def test_huge_integers_are_nonfinite_not_overflow_errors() -> None:
    with pytest.raises(SystemOnePromptsError) as caught:
        create_factor_evaluator({"f": {"ref": "q", "score": {"gte": 10**400}}})
    assert caught.value.diagnostics[0].code == "comparator-number"
    evaluate = create_factor_evaluator({"f": {"all": ["q"]}})
    with pytest.raises(SystemOnePromptsError) as runtime:
        evaluate({"q": {"type": "noul", "noul": 10**400}})
    assert runtime.value.diagnostics[0].code == "nonfinite-number"
    predicate = create_factor_evaluator({"f": {"ref": "q", "known": True}})
    # A huge integer is not a finite number, so the answer is unknown rather than an error.
    assert predicate({"q": {"type": "noul", "noul": 10**400}}) == {"f": False}


def test_eager_all_any_validation() -> None:
    definition = parse_definition(
        """
[questions.a]
type = "noul"
[factors]
bad = { all = [] }
"""
    )
    assert any(item.code == "factor-list" for item in check_definition(definition))
