"""Factor parsing, validation, and pure answer evaluation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any

from .diagnostics import Diagnostic, SourceLocation, SystemOnePromptsError, diagnostic, errors_of
from .json_values import is_plain_object
from .locate import EMPTY_INDEX, SourceIndex, locate

NOUL_CUTOFF = 0.5
COMPARATOR_KEYS = ("gt", "gte", "lt", "lte")
OPERATOR_KEYS = ("all", "any", "not", "at_least")
OPERATOR_ALLOWED = {
    "all": {"all"},
    "any": {"any"},
    "not": {"not"},
    "at_least": {"at_least", "of"},
}
PREDICATE_ALLOWED = {"ref", "known", "choice", "noul", "score", "confidence"}


@dataclass(frozen=True, slots=True)
class Factor:
    kind: str
    ref: str | None = None
    known: bool | None = None
    choice: str | None = None
    noul: dict[str, float] | None = None
    score: dict[str, float] | None = None
    confidence: dict[str, float] | None = None
    of: tuple[str, ...] = ()
    count: int | None = None


def referenced_ids(factor: Factor) -> tuple[str, ...]:
    if factor.kind == "predicate":
        return (factor.ref,) if factor.ref else ()
    return factor.of


def parse_factors(
    raw: Any,
    question_ids: set[str],
    index: SourceIndex | None = None,
) -> tuple[dict[str, Factor], dict[str, dict[str, Any]], list[Diagnostic]]:
    source = index or EMPTY_INDEX
    factors: dict[str, Factor] = {}
    definitions: dict[str, dict[str, Any]] = {}
    diagnostics: list[Diagnostic] = []
    if raw is None:
        return factors, definitions, diagnostics
    if not is_plain_object(raw):
        diagnostics.append(
            diagnostic(
                "error",
                "factors-not-table",
                "[factors] must be a table of Boolean derivations",
                locate(source, table="factors"),
            )
        )
        return factors, definitions, diagnostics
    for factor_id, raw_factor in raw.items():
        location = locate(source, section="factors", key=str(factor_id), table="factors")
        if factor_id in question_ids:
            diagnostics.append(
                diagnostic(
                    "error",
                    "id-collision",
                    f"factor `{factor_id}` collides with question `{factor_id}`",
                    location,
                )
            )
            continue
        if not is_plain_object(raw_factor):
            diagnostics.append(
                diagnostic(
                    "error",
                    "factor-not-table",
                    f"factor `{factor_id}` must be an inline table",
                    location,
                )
            )
            continue
        parsed, item_diagnostics = _parse_factor(str(factor_id), raw_factor, location)
        diagnostics.extend(item_diagnostics)
        if parsed is not None:
            factors[str(factor_id)] = parsed
            definitions[str(factor_id)] = dict(raw_factor)
    return factors, definitions, diagnostics


def _parse_factor(
    factor_id: str, value: dict[str, Any], location: SourceLocation
) -> tuple[Factor | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    has_ref = "ref" in value
    operators = [key for key in OPERATOR_KEYS if key in value]
    if has_ref and operators:
        return None, [
            diagnostic(
                "error",
                "factor-mixed",
                f"factor `{factor_id}` cannot mix a predicate `ref` with Boolean operators",
                location,
            )
        ]
    if len(operators) > 1:
        return None, [
            diagnostic(
                "error",
                "factor-mixed",
                f"factor `{factor_id}` uses several operators ({', '.join(operators)}); use exactly one",
                location,
                "nest them as separate factors instead",
            )
        ]
    allowed = PREDICATE_ALLOWED if has_ref else OPERATOR_ALLOWED[operators[0] if operators else "at_least"]
    unknown = [key for key in value if key not in allowed]
    for key in unknown:
        diagnostics.append(
            diagnostic(
                "error",
                "unknown-factor-field",
                f"factor `{factor_id}` has unknown field `{key}`",
                location,
            )
        )
    if unknown:
        return None, diagnostics
    if has_ref:
        return _parse_predicate(factor_id, value, location, diagnostics)
    if "at_least" in value or ("of" in value and not operators):
        return _parse_at_least(factor_id, value, location, diagnostics)
    if "all" in value:
        values = _read_string_list(factor_id, "all", value.get("all"), location, diagnostics)
        if values is None:
            return None, diagnostics
        return Factor("all", of=tuple(values)), diagnostics
    if "any" in value:
        values = _read_string_list(factor_id, "any", value.get("any"), location, diagnostics)
        if values is None:
            return None, diagnostics
        return Factor("any", of=tuple(values)), diagnostics
    if "not" in value:
        if not isinstance(value.get("not"), str):
            return None, [
                diagnostic(
                    "error",
                    "factor-not",
                    f"factor `{factor_id}` `not` must be a string id",
                    location,
                )
            ]
        return Factor("not", of=(value["not"],)), diagnostics
    return None, [
        diagnostic(
            "error",
            "factor-empty",
            f"factor `{factor_id}` must be a predicate or a Boolean operator",
            location,
            "use ref / all / any / not / at_least",
        )
    ]


def _parse_predicate(
    factor_id: str,
    value: dict[str, Any],
    location: SourceLocation,
    diagnostics: list[Diagnostic],
) -> tuple[Factor | None, list[Diagnostic]]:
    ref = value.get("ref")
    if not isinstance(ref, str) or not ref:
        diagnostics.append(
            diagnostic(
                "error", "predicate-ref", f"factor `{factor_id}` `ref` must be a question id", location
            )
        )
        return None, diagnostics
    known = value.get("known") if "known" in value else None
    if "known" in value and type(known) is not bool:
        diagnostics.append(
            diagnostic(
                "error",
                "predicate-known",
                f"factor `{factor_id}` `known` must be a boolean",
                location,
            )
        )
        return None, diagnostics
    choice = value.get("choice") if "choice" in value else None
    if "choice" in value and not isinstance(choice, str):
        diagnostics.append(
            diagnostic(
                "error",
                "predicate-choice",
                f"factor `{factor_id}` `choice` must be a string label",
                location,
            )
        )
        return None, diagnostics
    comparators: dict[str, dict[str, float]] = {}
    for field_name in ("noul", "score", "confidence"):
        # Only an absent key is skipped; an explicit `null` is a value and fails below.
        if field_name not in value:
            continue
        comparator = _parse_comparator(factor_id, field_name, value[field_name], location, diagnostics)
        if comparator is None:
            return None, diagnostics
        comparators[field_name] = comparator
    if (
        known is None
        and choice is None
        and "noul" not in comparators
        and "score" not in comparators
        and "confidence" not in comparators
    ):
        diagnostics.append(
            diagnostic(
                "error",
                "predicate-empty",
                f"factor `{factor_id}` predicate needs one of known / choice / noul / score / confidence",
                location,
            )
        )
        return None, diagnostics
    return (
        Factor(
            "predicate",
            ref=ref,
            known=known,
            choice=choice,
            noul=comparators.get("noul"),
            score=comparators.get("score"),
            confidence=comparators.get("confidence"),
        ),
        diagnostics,
    )


def _is_positive_integer(value: Any) -> bool:
    if type(value) is int:
        return value >= 1
    if type(value) is float:
        return value.is_integer() and value >= 1
    return False


def _parse_at_least(
    factor_id: str,
    value: dict[str, Any],
    location: SourceLocation,
    diagnostics: list[Diagnostic],
) -> tuple[Factor | None, list[Diagnostic]]:
    count = value.get("at_least")
    if not _is_positive_integer(count):
        diagnostics.append(
            diagnostic(
                "error",
                "at-least-count",
                f"factor `{factor_id}` `at_least` must be a positive integer",
                location,
            )
        )
        return None, diagnostics
    values = _read_string_list(factor_id, "of", value.get("of"), location, diagnostics)
    if values is None:
        return None, diagnostics
    integer_count = int(count) if isinstance(count, int | float) else 1
    return Factor("at_least", of=tuple(values), count=integer_count), diagnostics


def _parse_comparator(
    factor_id: str,
    field_name: str,
    value: Any,
    location: SourceLocation,
    diagnostics: list[Diagnostic],
) -> dict[str, float] | None:
    if not is_plain_object(value):
        diagnostics.append(
            diagnostic(
                "error",
                "comparator-table",
                f"factor `{factor_id}` `{field_name}` must be a comparator table",
                location,
                "e.g. { gte = 0.75 }",
            )
        )
        return None
    unknown = [key for key in value if key not in COMPARATOR_KEYS]
    if unknown:
        diagnostics.append(
            diagnostic(
                "error",
                "comparator-keys",
                f"factor `{factor_id}` `{field_name}` has unknown comparator "
                + ", ".join(f"`{key}`" for key in unknown),
                location,
                "use gt, gte, lt, lte",
            )
        )
        return None
    output: dict[str, float] = {}
    for key in COMPARATOR_KEYS:
        if key not in value:
            continue
        number = finite_float(value[key])
        if number is None:
            diagnostics.append(
                diagnostic(
                    "error",
                    "comparator-number",
                    f"factor `{factor_id}` `{field_name}.{key}` must be a finite number",
                    location,
                )
            )
            return None
        output[key] = number
    if not output:
        diagnostics.append(
            diagnostic(
                "error",
                "comparator-empty",
                f"factor `{factor_id}` `{field_name}` needs at least one of gt/gte/lt/lte",
                location,
            )
        )
        return None
    return output


def _read_string_list(
    factor_id: str,
    field_name: str,
    value: Any,
    location: SourceLocation,
    diagnostics: list[Diagnostic],
) -> list[str] | None:
    if type(value) is not list or not value or not all(isinstance(item, str) for item in value):
        diagnostics.append(
            diagnostic(
                "error",
                "factor-list",
                f"factor `{factor_id}` `{field_name}` must be a non-empty array of ids",
                location,
            )
        )
        return None
    return list(value)


def validate_primitive_refs(
    factor_id: str,
    factor: Factor,
    questions: dict[str, dict[str, Any]],
    factor_ids: set[str],
    location: SourceLocation,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if factor.kind == "predicate":
        question = questions.get(factor.ref or "")
        if question is None:
            diagnostics.append(
                diagnostic(
                    "error",
                    "unknown-ref",
                    f"factor `{factor_id}` references unknown question `{factor.ref}`",
                    location,
                )
            )
            return diagnostics
        question_type = question.get("type")
        if factor.choice is not None:
            if question_type != "choice":
                diagnostics.append(
                    diagnostic(
                        "error",
                        "choice-on-non-choice",
                        f"`choice` is not available on {str(question_type).capitalize()} `{factor.ref}`",
                        location,
                    )
                )
            else:
                labels = question.get("criteria")
                if not isinstance(labels, dict) or factor.choice not in labels:
                    diagnostics.append(
                        diagnostic(
                            "error",
                            "unknown-option",
                            f"factor `{factor_id}` references Choice `{factor.ref}` with unknown option `{factor.choice}`",
                            location,
                            "available: " + (", ".join(labels) if isinstance(labels, dict) else ""),
                        )
                    )
        if factor.noul is not None and question_type != "noul":
            diagnostics.append(
                diagnostic(
                    "error",
                    "noul-on-non-noul",
                    f"`noul` is not available on {str(question_type).capitalize()} `{factor.ref}`",
                    location,
                )
            )
        if factor.score is not None and question_type != "score":
            diagnostics.append(
                diagnostic(
                    "error",
                    "score-on-non-score",
                    f"`score` is not available on {str(question_type).capitalize()} `{factor.ref}`",
                    location,
                )
            )
        if factor.confidence is not None and question_type == "noul":
            diagnostics.append(
                diagnostic(
                    "error",
                    "noul-confidence",
                    f"`confidence` is not available on Noul `{factor.ref}` (Noul answers carry only `noul`)",
                    location,
                )
            )
        return diagnostics

    for ref in referenced_ids(factor):
        if ref in factor_ids or ref in questions:
            question = questions.get(ref)
            if question is not None and question.get("type") != "noul":
                question_type = str(question.get("type"))
                wrapper = 'choice = "…"' if question_type == "choice" else "score = { gte = … }"
                diagnostics.append(
                    diagnostic(
                        "error",
                        "non-boolean-ref",
                        f"{question_type.capitalize()} `{ref}` used directly in `{factor.kind}`; wrap it in a predicate: {{ ref = \"{ref}\", {wrapper} }}",
                        location,
                    )
                )
            continue
        diagnostics.append(
            diagnostic(
                "error",
                "unknown-ref",
                f"factor `{factor_id}` references unknown id `{ref}`",
                location,
            )
        )
    return diagnostics


def topo_sort_factors(
    factors: dict[str, Factor],
    locate_factor: Any = None,
) -> tuple[list[str], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    factor_ids = set(factors)
    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []
    stack: list[str] = []

    def visit(factor_id: str) -> None:
        if factor_id in visited:
            return
        if factor_id in visiting:
            start = stack.index(factor_id)
            cycle = [*stack[start:], factor_id]
            # Like the TypeScript walker, every back edge reports (a duplicate operand
            # such as `all = ["s", "s"]` yields the same cycle twice).
            location = locate_factor(factor_id) if locate_factor else SourceLocation()
            diagnostics.append(
                diagnostic("error", "cycle", "cycle: " + " → ".join(cycle), location)
            )
            return
        visiting.add(factor_id)
        stack.append(factor_id)
        factor = factors[factor_id]
        for ref in referenced_ids(factor):
            if ref in factor_ids:
                visit(ref)
        stack.pop()
        visiting.remove(factor_id)
        visited.add(factor_id)
        order.append(factor_id)

    for factor_id in factors:
        visit(factor_id)
    return order, diagnostics


def compare(value: float, comparator: dict[str, float]) -> bool:
    _require_finite("comparison", "value", value)
    for key, bound in comparator.items():
        _require_finite("comparison", key, bound)
    if "gt" in comparator and not value > comparator["gt"]:
        return False
    if "gte" in comparator and not value >= comparator["gte"]:
        return False
    if "lt" in comparator and not value < comparator["lt"]:
        return False
    if "lte" in comparator and not value <= comparator["lte"]:
        return False
    return True


def finite_float(value: Any) -> float | None:
    """`value` as a finite float, or None for non-numbers, bools, NaN/inf, and ints too
    large for IEEE-754 (which JavaScript would already have read as Infinity)."""
    if type(value) is not int and type(value) is not float:
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if isfinite(number) else None


def is_known_native_answer(answer: Any) -> bool:
    if not is_plain_object(answer) or answer.get("missing") is True:
        return False
    if "confidence" in answer:
        confidence = finite_float(answer["confidence"])
        return confidence is not None and confidence != 0
    if "noul" in answer:
        noul = finite_float(answer["noul"])
        return noul is not None and noul != NOUL_CUTOFF
    if isinstance(answer.get("choice"), str):
        return True
    return finite_float(answer.get("score")) is not None


def create_factor_evaluator(
    definitions: Mapping[str, Any],
) -> Callable[[Mapping[str, Any]], dict[str, bool]]:
    if not isinstance(definitions, Mapping):
        raise SystemOnePromptsError(
            diagnostic(
                "error",
                "factors-not-table",
                "create_factor_evaluator expects the factor tables (definition.factor_definitions)",
            )
        )
    snapshot = {str(key): dict(value) if isinstance(value, dict) else value for key, value in definitions.items()}
    factors, _, diagnostics = parse_factors(snapshot, set(), EMPTY_INDEX)
    if errors_of(diagnostics):
        raise SystemOnePromptsError(errors_of(diagnostics))
    order, cycle_diagnostics = topo_sort_factors(factors)
    if cycle_diagnostics:
        raise SystemOnePromptsError(cycle_diagnostics)
    factor_ids = list(snapshot)

    def evaluate(answers: Mapping[str, Any]) -> dict[str, bool]:
        resolved: dict[str, bool] = {}
        for factor_id in order:
            resolved[factor_id] = _evaluate_factor(
                factor_id, factors[factor_id], answers, resolved, factors
            )
        return {factor_id: resolved.get(factor_id, False) for factor_id in factor_ids}

    return evaluate


def _evaluate_factor(
    factor_id: str,
    factor: Factor,
    answers: Mapping[str, Any],
    resolved: dict[str, bool],
    factors: dict[str, Factor],
) -> bool:
    if factor.kind == "predicate":
        return _evaluate_predicate(factor_id, factor, answers)
    if factor.kind == "not":
        return not _resolve_bool(factor.of[0], answers, resolved, factors)
    if factor.kind == "all":
        result = True
        for ref in factor.of:
            if not _resolve_bool(ref, answers, resolved, factors):
                result = False
        return result
    if factor.kind == "any":
        result = False
        for ref in factor.of:
            if _resolve_bool(ref, answers, resolved, factors):
                result = True
        return result
    count = 0
    for ref in factor.of:
        if _resolve_bool(ref, answers, resolved, factors):
            count += 1
    return count >= (factor.count or 0)


def _has_value_checks(factor: Factor) -> bool:
    # Presence, not truthiness: `choice = ""` is a real label check.
    return (
        factor.choice is not None
        or factor.noul is not None
        or factor.score is not None
        or factor.confidence is not None
    )


def _evaluate_predicate(factor_id: str, factor: Factor, answers: Mapping[str, Any]) -> bool:
    ref = factor.ref
    looked_up = answers[ref] if ref is not None and ref in answers else None
    known = is_known_native_answer(looked_up)
    if factor.known is not None:
        if factor.known != known:
            return False
        if not _has_value_checks(factor):
            return True
        if factor.known is False and (looked_up is None or not is_plain_object(looked_up)):
            raise SystemOnePromptsError(
                diagnostic("error", "missing-answer", f"missing answer `{factor.ref}`")
            )
    answer = _require_answer(factor.ref or "", answers)
    if not is_plain_object(answer):
        raise SystemOnePromptsError(
            diagnostic("error", "invalid-answer", f"answer `{factor.ref}` is not an object")
        )
    checks: list[bool] = []
    if factor.choice is not None:
        if not isinstance(answer.get("choice"), str):
            raise SystemOnePromptsError(
                diagnostic(
                    "error",
                    "missing-choice-field",
                    f"factor `{factor_id}` expected Choice answer `{factor.ref}` to have a choice field",
                )
            )
        checks.append(answer["choice"] == factor.choice)
    for field_name, comparator in (
        ("noul", factor.noul),
        ("score", factor.score),
        ("confidence", factor.confidence),
    ):
        if comparator is None:
            continue
        value = answer.get(field_name) if field_name in answer else None
        if type(value) is not int and type(value) is not float:
            raise SystemOnePromptsError(
                diagnostic(
                    "error",
                    f"missing-{field_name}-field",
                    f"factor `{factor_id}` expected "
                    + (
                        f"Noul answer `{factor.ref}` to have a noul field"
                        if field_name == "noul"
                        else f"Score answer `{factor.ref}` to have a score field"
                        if field_name == "score"
                        else f"`{factor.ref}` to have a confidence field"
                    ),
                )
            )
        number = _require_finite(f"factor `{factor_id}` answer `{factor.ref}`", field_name, value)
        checks.append(compare(number, comparator))
    return all(checks)


def _resolve_bool(
    ref: str, answers: Mapping[str, Any], resolved: dict[str, bool], factors: dict[str, Factor]
) -> bool:
    if ref in resolved:
        return resolved[ref]
    if ref in factors:
        raise SystemOnePromptsError(
            diagnostic(
                "error",
                "factor-order",
                f"factor `{ref}` was referenced before it was evaluated",
            )
        )
    answer = _require_answer(ref, answers)
    if not is_plain_object(answer) or "noul" not in answer or type(answer["noul"]) not in {int, float}:
        raise SystemOnePromptsError(
            diagnostic(
                "error",
                "non-noul-runtime",
                f"reference `{ref}` is not a Noul answer; wrap Choice/Score in a predicate",
            )
        )
    return _require_finite(f"answer `{ref}`", "noul", answer["noul"]) >= NOUL_CUTOFF


def _require_answer(answer_id: str, answers: Mapping[str, Any]) -> Any:
    if answer_id not in answers or answers[answer_id] is None:
        raise SystemOnePromptsError(diagnostic("error", "missing-answer", f"missing answer `{answer_id}`"))
    return answers[answer_id]


def _require_finite(context: str, field: str, value: Any) -> float:
    number = finite_float(value)
    if number is None:
        raise SystemOnePromptsError(
            diagnostic("error", "nonfinite-number", f"{context} field `{field}` must be finite")
        )
    return number


__all__ = [
    "COMPARATOR_KEYS",
    "Factor",
    "NOUL_CUTOFF",
    "compare",
    "create_factor_evaluator",
    "finite_float",
    "is_known_native_answer",
    "parse_factors",
    "referenced_ids",
    "topo_sort_factors",
    "validate_primitive_refs",
]
