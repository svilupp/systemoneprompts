"""State path parsing and runtime assertions for ``[requires]``."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, Literal, cast

from .diagnostics import Diagnostic, SystemOnePromptsError, diagnostic, errors_of
from .json_values import is_json_value, is_plain_object, js_string, type_name
from .locate import EMPTY_INDEX, SourceIndex, locate

RequirementType = Literal["string", "number", "boolean", "array", "object", "null", "exists"]
REQUIREMENT_TYPES = ("string", "number", "boolean", "array", "object", "null", "exists")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INDEX = re.compile(r"\[([0-9]+)\]")
MAX_INDEX = 2**32 - 2
_MISSING = object()


class AllIndex:
    __slots__ = ()

    def __repr__(self) -> str:
        return "ALL_INDEX"


ALL_INDEX = AllIndex()
PathSegment = str | int | AllIndex


def parse_path(path: str) -> list[PathSegment] | None:
    if not path:
        return None
    match = _IDENT.match(path)
    if match is None:
        return None
    result: list[PathSegment] = [match.group(0)]
    cursor = match.end()
    while cursor < len(path):
        if path[cursor] == ".":
            match = _IDENT.match(path, cursor + 1)
            if match is None:
                return None
            result.append(match.group(0))
            cursor = match.end()
            continue
        if path.startswith("[]", cursor):
            result.append(ALL_INDEX)
            cursor += 2
            continue
        match = _INDEX.match(path, cursor)
        if match is None:
            return None
        index = int(match.group(1))
        if index > MAX_INDEX:
            return None
        result.append(index)
        cursor = match.end()
    return result


def format_path(segments: list[PathSegment]) -> str:
    output = ""
    for segment in segments:
        if isinstance(segment, str):
            output = segment if not output else f"{output}.{segment}"
        elif segment is ALL_INDEX:
            output += "[]"
        else:
            output += f"[{segment}]"
    return output


def _same_segment(left: PathSegment, right: PathSegment) -> bool:
    if left is ALL_INDEX or right is ALL_INDEX:
        return left is right
    return type(left) is type(right) and left == right


def _conflict_same_segment(left: PathSegment, right: PathSegment) -> bool:
    """`[]` covers `[n]` for conflict analysis; distinct indexes stay distinct."""
    if _same_segment(left, right):
        return True
    return _implies_array(left) and _implies_array(right) and (left is ALL_INDEX or right is ALL_INDEX)


def _implies_array(segment: PathSegment) -> bool:
    return segment is ALL_INDEX or isinstance(segment, int)


def path_guarantees_token(required: list[PathSegment], token: list[PathSegment]) -> bool:
    """True when a required path guarantees a backticked token, including prefixes."""
    for index, token_segment in enumerate(token):
        if index >= len(required):
            return False
        if not _segment_guarantees(required[index], token_segment):
            return False
    return True


def _segment_guarantees(required: PathSegment, token: PathSegment) -> bool:
    if type(required) is str and type(token) is str:
        return required == token
    if type(required) is int and type(token) is int:
        return required == token
    if required is ALL_INDEX and token is ALL_INDEX:
        return True
    return required is ALL_INDEX and type(token) is int


def check_requirement_conflicts(
    requirements: Mapping[str, RequirementType],
    index: SourceIndex | None = None,
) -> list[Diagnostic]:
    """Reject explicit and implied object/array type conflicts, comparing canonical indexes."""
    source = index or EMPTY_INDEX
    entries = [
        (path, expected, parsed, format_path(parsed))
        for path, expected in requirements.items()
        if (parsed := parse_path(path)) is not None
    ]
    diagnostics: list[Diagnostic] = []
    explicit_types = {canonical for _, expected, _, canonical in entries if expected != "exists"}
    reported_mixed: set[str] = set()
    for left_index, (left_path, left_type, left_segments, _) in enumerate(entries):
        for right_path, right_type, right_segments, _ in entries[left_index + 1 :]:
            common = 0
            while (
                common < len(left_segments)
                and common < len(right_segments)
                and _conflict_same_segment(left_segments[common], right_segments[common])
            ):
                common += 1
            left_ends = common == len(left_segments)
            right_ends = common == len(right_segments)
            if left_ends or right_ends:
                if left_ends and right_ends:
                    if left_type != right_type and "exists" not in {left_type, right_type}:
                        diagnostics.append(
                            diagnostic(
                                "error",
                                "require-conflict",
                                f"[requires] `{left_path}` is required as both `{left_type}` and `{right_type}`",
                                locate(source, section="requires", key=left_path, table="requires"),
                                "keep one compatible requirement for this path",
                            )
                        )
                    continue
                parent_path, parent_type = (
                    (left_path, left_type) if left_ends else (right_path, right_type)
                )
                child_path = right_path if left_ends else left_path
                if parent_type == "exists":
                    continue
                next_segment = (right_segments if left_ends else left_segments)[common]
                container = "array" if _implies_array(next_segment) else "object"
                if parent_type != container:
                    detail = (
                        f"requires it to be an {container}"
                        if parent_type in {"object", "array"}
                        else "requires it to be a container"
                    )
                    diagnostics.append(
                        diagnostic(
                            "error",
                            "require-conflict",
                            f"[requires] `{parent_path}` is `{parent_type}` but `{child_path}` {detail}",
                            locate(
                                source, section="requires", key=parent_path, table="requires"
                            ),
                            f'change `{parent_path}` to "{container}" or "exists", or drop it',
                        )
                    )
                continue
            left_next, right_next = left_segments[common], right_segments[common]
            if type(left_next) is type(right_next):
                continue
            prefix = format_path(left_segments[:common])
            if prefix in explicit_types or prefix in reported_mixed:
                continue
            reported_mixed.add(prefix)
            diagnostics.append(
                diagnostic(
                    "error",
                    "require-conflict",
                    f"[requires] `{left_path}` and `{right_path}` require `{prefix}` to be both an array and an object",
                    locate(source, section="requires", key=left_path, table="requires"),
                    f"use either dotted keys or [n] indexes under `{prefix}`",
                )
            )
    return diagnostics


def parse_requirements(
    raw: Any, index: SourceIndex
) -> tuple[dict[str, RequirementType], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    requirements: dict[str, RequirementType] = {}
    if raw is None:
        return requirements, diagnostics
    if not is_plain_object(raw):
        diagnostics.append(
            diagnostic(
                "error",
                "requires-not-table",
                "[requires] must be a table of path = type entries",
                locate(index, table="requires"),
            )
        )
        return requirements, diagnostics
    for path, expected in raw.items():
        location = locate(index, section="requires", key=str(path), table="requires")
        if not isinstance(path, str) or parse_path(path) is None:
            diagnostics.append(
                diagnostic(
                    "error",
                    "invalid-require-path",
                    f"invalid [requires] path `{path}`",
                    location,
                    "use dotted identifiers and [n] or [] indexes, e.g. ticket.message or tickets[0].id",
                )
            )
        elif expected not in REQUIREMENT_TYPES:
            diagnostics.append(
                diagnostic(
                    "error",
                    "invalid-require-type",
                    f"[requires] `{path}` has unknown type "
                    + ("undefined" if expected is None else f"`{js_string(expected)}`"),
                    location,
                    "expected " + " | ".join(REQUIREMENT_TYPES),
                )
            )
        else:
            requirements[path] = expected
    return requirements, diagnostics


def get_at_path(state: Any, segments: list[PathSegment]) -> Any:
    current = state
    for segment in segments:
        if segment is ALL_INDEX:
            return _MISSING
        if isinstance(segment, int):
            if type(current) is not list or segment < 0 or segment >= len(current):
                return _MISSING
            current = current[segment]
        else:
            # Any mapping is traversable (TypeScript walks any non-array object); the
            # `object` requirement itself still demands a plain JSON object.
            if type(current) is list or not isinstance(current, Mapping) or segment not in current:
                return _MISSING
            current = current[segment]
    return current


def _matches(expected: RequirementType, value: Any) -> bool:
    if expected == "exists":
        return value is not _MISSING
    if value is _MISSING:
        return False
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return type(value) in {int, float} and value == value and value not in {
            float("inf"),
            float("-inf"),
        }
    if expected == "boolean":
        return type(value) is bool
    if expected == "array":
        return type(value) is list and is_json_value(value)
    if expected == "object":
        return is_plain_object(value) and is_json_value(value)
    return value is None


def _assert_segments(
    current: Any,
    segments: list[PathSegment],
    path: str,
    expected: RequirementType,
) -> Diagnostic | None:
    if not segments:
        if _matches(expected, current):
            return None
        got = "undefined" if current is _MISSING else type_name(current)
        return diagnostic("error", "state-requirement", f"{path}: expected {expected}, got {got}")
    head, rest = segments[0], segments[1:]
    if head is ALL_INDEX:
        if type(current) is not list:
            return diagnostic(
                "error", "state-requirement", f"{path}: expected {expected}, got undefined"
            )
        if not current:
            return None
        for element in current:
            error = _assert_segments(element, rest, path, expected)
            if error is not None:
                return error
        return None
    return _assert_segments(get_at_path(current, [head]), rest, path, expected)


def create_state_assert(requirements: Mapping[str, str]) -> Callable[[Any], None]:
    """Build a runtime assertion. Invalid paths and type conflicts fail at construction."""
    if not isinstance(requirements, Mapping):
        raise SystemOnePromptsError(
            diagnostic(
                "error",
                "requires-not-table",
                "[requires] must be a table of path = type entries",
            )
        )
    compiled: list[tuple[str, RequirementType, list[PathSegment]]] = []
    typed: dict[str, RequirementType] = {}
    for path, expected in requirements.items():
        if not isinstance(path, str):
            raise SystemOnePromptsError(
                diagnostic("error", "invalid-require-path", f"invalid [requires] path `{path!r}`")
            )
        if expected not in REQUIREMENT_TYPES:
            raise SystemOnePromptsError(
                diagnostic(
                    "error",
                    "invalid-require-type",
                    f"[requires] `{path}` has unknown type `{js_string(expected)}`",
                )
            )
        segments = parse_path(path)
        if segments is None:
            raise SystemOnePromptsError(
                diagnostic("error", "invalid-require-path", f"invalid [requires] path `{path}`")
            )
        typed[path] = cast(RequirementType, expected)
        compiled.append((format_path(segments), cast(RequirementType, expected), segments))
    conflicts = errors_of(check_requirement_conflicts(typed))
    if conflicts:
        raise SystemOnePromptsError(conflicts)

    def assert_state(state: Any) -> None:
        for path, expected, segments in compiled:
            error = _assert_segments(state, segments, path, expected)
            if error is not None:
                raise SystemOnePromptsError(error)

    return assert_state


__all__ = [
    "ALL_INDEX",
    "REQUIREMENT_TYPES",
    "RequirementType",
    "check_requirement_conflicts",
    "create_state_assert",
    "format_path",
    "get_at_path",
    "parse_path",
    "parse_requirements",
]
