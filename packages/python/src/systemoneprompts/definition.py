"""Parse and validate the portable ``.toml`` definition format."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .diagnostics import (
    Diagnostic,
    SourceLocation,
    SystemOnePromptsError,
    diagnostic,
    nearest_match,
)
from .factors import Factor, parse_factors, topo_sort_factors, validate_primitive_refs
from .json_values import is_json_value, is_plain_object, js_key_order
from .locate import SourceIndex, index_source, locate, split_lines
from .questions import lint_backticks, validate_questions
from .requirements import RequirementType, check_requirement_conflicts, parse_requirements

KNOWN_TOP_LEVEL = (
    "title",
    "version",
    "description",
    "model",
    "provider",
    "requires",
    "questions",
    "factors",
    "data",
)
META_KEYS = ("title", "version", "description")
KNOWN_TABLES = ("requires", "questions", "factors", "data")
_TOML_POSITION = re.compile(r"\(at line (\d+), column (\d+)\)")
# JavaScript `Number.MAX_SAFE_INTEGER`; smol-toml rejects TOML integers beyond it.
_SAFE_INTEGER = 2**53 - 1
_INTEGER_LITERAL = re.compile(r"(?<![\w.])(?:0x[0-9A-Fa-f_]+|0o[0-7_]+|0b[01_]+|[+-]?\d[\d_]*)(?![\w.])")


@dataclass(slots=True)
class Definition:
    meta: dict[str, Any]
    model: str | None
    requires: dict[str, RequirementType]
    questions: dict[str, dict[str, Any]]
    factors: dict[str, Factor]
    factor_definitions: dict[str, dict[str, Any]]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    source: str | None = None
    filename: str | None = None
    source_index: SourceIndex = field(default_factory=SourceIndex)
    # Append optional fields so existing positional constructors remain valid.
    data: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None


def parse_definition(source: str, *, filename: str | None = None) -> Definition:
    try:
        raw = js_key_order(tomllib.loads(source))
    except tomllib.TOMLDecodeError as error:
        raise _wrap_toml_error(error, filename, source) from error
    unsafe = _find_unsafe_integer(raw)
    if unsafe is not None:
        raise _unsafe_integer_error(unsafe, filename, source)
    if not is_plain_object(raw):
        raise SystemOnePromptsError(
            diagnostic("error", "toml-root", "definition must be a TOML table", diagnostic_location(filename, 1))
        )

    index = index_source(source, filename)
    diagnostics: list[Diagnostic] = []
    meta: dict[str, Any] = {}
    for key in META_KEYS:
        if key not in raw:
            continue
        if isinstance(raw[key], str):
            meta[key] = raw[key]
        else:
            diagnostics.append(
                diagnostic(
                    "error",
                    "meta-string",
                    f"`{key}` must be a string",
                    locate(index, key=key),
                )
            )

    provider = None
    if "provider" in raw:
        if raw["provider"] in ("typesafe", "openai"):
            provider = raw["provider"]
            meta["provider"] = provider
        else:
            diagnostics.append(diagnostic("error", "provider-value", '`provider` must be "typesafe" or "openai"', locate(index, key="provider")))
    model: str | None = None
    if "model" in raw:
        if isinstance(raw["model"], str) and raw["model"].strip():
            model = raw["model"].strip()
        else:
            diagnostics.append(
                diagnostic(
                    "error",
                    "model-string",
                    "`model` must be a non-empty string",
                    locate(index, key="model"),
                )
            )

    data: dict[str, Any] = {}
    if "data" in raw:
        candidate = raw["data"]
        if not is_plain_object(candidate):
            diagnostics.append(
                diagnostic(
                    "error",
                    "data-type",
                    "`data` must be a TOML table",
                    locate(index, key="data"),
                )
            )
        elif not is_json_value(candidate):
            invalid_path = _first_invalid_json_path(candidate)
            path_text = _format_data_path(invalid_path)
            diagnostics.append(
                diagnostic(
                    "error",
                    "data-json",
                    f"`data{path_text}` must contain only JSON-compatible values",
                    _locate_data_path(index, invalid_path),
                )
            )
        else:
            # js_key_order has already been applied to the complete TOML tree,
            # matching the JavaScript object enumeration order.
            data = candidate

    for key, value in raw.items():
        if key in KNOWN_TOP_LEVEL:
            continue
        if is_plain_object(value) or type(value) is list:
            suggestion = nearest_match(key, KNOWN_TABLES)
            diagnostics.append(
                diagnostic(
                    "warning",
                    "unknown-table",
                    f"unknown top-level table [{key}]",
                    locate(index, table=key, key=key),
                    f"did you mean [{suggestion}]?" if suggestion else None,
                )
            )
            continue
        if type(value) in {str, int, float, bool}:
            meta[key] = value

    requires, requirement_diagnostics = parse_requirements(raw.get("requires"), index)
    questions, question_diagnostics = validate_questions(raw.get("questions"), index)
    factors, factor_definitions, factor_diagnostics = parse_factors(
        raw.get("factors"), set(questions), index
    )
    diagnostics.extend(requirement_diagnostics)
    diagnostics.extend(question_diagnostics)
    diagnostics.extend(factor_diagnostics)
    return Definition(
        meta=meta,
        model=model,
        provider=provider,
        requires=requires,
        questions=questions,
        factors=factors,
        factor_definitions=factor_definitions,
        diagnostics=diagnostics,
        source=source,
        filename=filename,
        source_index=index,
        data=data,
    )


def _first_invalid_json_path(value: Any) -> tuple[str | int, ...]:
    """Return a best-effort path to the first non-JSON value in ``value``."""
    if is_json_value(value):
        return ()
    if type(value) is list:
        for position, item in enumerate(value):
            if not is_json_value(item):
                child = _first_invalid_json_path(item)
                return (position, *child)
    elif is_plain_object(value):
        for key, item in value.items():
            if not is_json_value(item):
                child = _first_invalid_json_path(item)
                return (key, *child)
    return ()


def _format_data_path(path: tuple[str | int, ...]) -> str:
    rendered = ""
    for segment in path:
        if isinstance(segment, int):
            rendered += f"[{segment}]"
        else:
            rendered += f"[{segment!r}]"
    return rendered


def _locate_data_path(index: SourceIndex, path: tuple[str | int, ...]) -> SourceLocation:
    """Locate the nearest source key/table for a data descendant."""
    for segment in path:
        if isinstance(segment, str):
            location = locate(index, section="data", key=segment)
            if location.line is not None:
                return location
            return locate(index, table="data")
        # Array indexes have no standalone TOML key location. Keep the nearest
        # data table location rather than inventing a source line.
    return locate(index, key="data")


def read_source(path: str) -> str:
    """Read a text file the way Node's `readFile(path, "utf8")` does.

    Line endings are preserved (no universal-newline translation, so a bare `\\r`
    still reaches the TOML parser) and invalid UTF-8 decodes to U+FFFD.
    """
    return Path(path).read_bytes().decode("utf-8", errors="replace")


def load_definition(path: str) -> Definition:
    return parse_definition(read_source(path), filename=path)


def check_definition(definition: Definition, *, strict: bool = False) -> list[Diagnostic]:
    diagnostics = list(definition.diagnostics)
    index = definition.source_index
    diagnostics.extend(check_requirement_conflicts(definition.requires, index))
    factor_ids = set(definition.factors)
    for factor_id, factor in definition.factors.items():
        diagnostics.extend(
            validate_primitive_refs(
                factor_id,
                factor,
                definition.questions,
                factor_ids,
                locate(index, section="factors", key=factor_id, table="factors"),
            )
        )
    _, cycle_diagnostics = topo_sort_factors(
        definition.factors,
        lambda factor_id: locate(index, section="factors", key=factor_id),
    )
    diagnostics.extend(cycle_diagnostics)
    diagnostics.extend(lint_backticks(definition.questions, definition.requires, index))
    if strict:
        diagnostics = [
            diagnostic("error", item.code, item.message, item.location, item.hint)
            if item.severity != "error"
            else item
            for item in diagnostics
        ]
    return diagnostics


def diagnostic_location(
    filename: str | None, line: int | None = None, column: int | None = None
) -> SourceLocation:
    return SourceLocation(filename, line, column)


def _wrap_toml_error(error: tomllib.TOMLDecodeError, filename: str | None, source: str) -> SystemOnePromptsError:
    message = str(error)
    line: int | None = None
    column: int | None = None
    if "at end of document" in message:
        # Python 3.14 exposes an EOF sentinel as ``lineno``/``colno`` (the
        # line after a trailing newline), while older versions only expose it
        # in the message. Point at the unterminated value's source line.
        lines = split_lines(source)
        if len(lines) > 1 and lines[-1] == "":
            lines.pop()  # a trailing newline does not start a new line
        line = max(1, len(lines))
        column = None
    else:
        line = getattr(error, "lineno", None)
        column = getattr(error, "colno", None)
    if not isinstance(line, int):
        match = _TOML_POSITION.search(message)
        if match:
            line = int(match.group(1))
            column = int(match.group(2))
        else:
            line = None
            column = None
    return SystemOnePromptsError(
        diagnostic("error", "toml-syntax", message, SourceLocation(filename, line, column))
    )


def _find_unsafe_integer(value: Any) -> int | None:
    """First TOML integer the reference parser cannot represent losslessly."""
    if type(value) is int:
        return value if abs(value) > _SAFE_INTEGER else None
    if type(value) is list:
        for item in value:
            found = _find_unsafe_integer(item)
            if found is not None:
                return found
    elif is_plain_object(value):
        for item in value.values():
            found = _find_unsafe_integer(item)
            if found is not None:
                return found
    return None


def _unsafe_integer_error(value: int, filename: str | None, source: str) -> SystemOnePromptsError:
    line: int | None = None
    column: int | None = None
    for number, text in enumerate(split_lines(source), 1):
        for match in _INTEGER_LITERAL.finditer(text):
            try:
                literal = int(match.group().replace("_", ""), 0)
            except ValueError:
                continue
            if literal == value:
                line, column = number, match.start() + 1
                break
        if line is not None:
            break
    return SystemOnePromptsError(
        diagnostic(
            "error",
            "toml-syntax",
            "integer value cannot be represented losslessly",
            SourceLocation(filename, line, column),
        )
    )


__all__ = [
    "Definition",
    "check_definition",
    "load_definition",
    "parse_definition",
    "read_source",
]
