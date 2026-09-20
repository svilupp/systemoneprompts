"""Structured diagnostics shared by parsing, validation, and CLI commands."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class SourceLocation:
    filename: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: Severity
    code: str
    message: str
    location: SourceLocation = SourceLocation()
    hint: str | None = None

    @property
    def detail(self) -> str | None:
        return self.hint

    @property
    def filename(self) -> str | None:
        return self.location.filename

    @property
    def line(self) -> int | None:
        return self.location.line

    @property
    def column(self) -> int | None:
        return self.location.column


class SystemOnePromptsError(Exception):
    """An operation failed with one or more user-facing diagnostics."""

    def __init__(self, diagnostics: Diagnostic | Iterable[Diagnostic]):
        if isinstance(diagnostics, Diagnostic):
            items = [diagnostics]
        else:
            items = list(diagnostics)
        if not items:
            raise TypeError("SystemOnePromptsError requires at least one diagnostic")
        self.diagnostics = items
        self.diagnostic = items[0]
        super().__init__("\n".join(format_diagnostic(item) for item in items))


def diagnostic(
    severity: Severity,
    code: str,
    message: str,
    location: SourceLocation | None = None,
    hint: str | None = None,
) -> Diagnostic:
    return Diagnostic(severity, code, message, location or SourceLocation(), hint)


def format_location(location: SourceLocation) -> str:
    if not location.filename and location.line is None:
        return ""
    name = location.filename or "<input>"
    if location.line is None:
        return name
    if location.column is None:
        return f"{name}:{location.line}"
    return f"{name}:{location.line}:{location.column}"


def format_diagnostic(item: Diagnostic) -> str:
    where = format_location(item.location)
    head = f"{where}  {item.message}" if where else item.message
    if not item.hint:
        return head
    indent = " " * (len(where) + 2) if where else "  "
    return f"{head}\n{indent}{item.hint}"


def errors_of(diagnostics: Iterable[Diagnostic]) -> list[Diagnostic]:
    return [item for item in diagnostics if item.severity == "error"]


def has_errors(diagnostics: Iterable[Diagnostic]) -> bool:
    return any(item.severity == "error" for item in diagnostics)


def nearest_match(needle: str, candidates: Iterable[str]) -> str | None:
    """Closest candidate by Levenshtein distance, or None when nothing is a plausible typo."""
    best: str | None = None
    best_score = float("inf")
    needle_units = _utf16_units(needle)
    for candidate in candidates:
        score = _levenshtein(needle_units, _utf16_units(candidate))
        if score < best_score:
            best = candidate
            best_score = score
    if best is None:
        return None
    # JavaScript `string.length` counts UTF-16 code units, so astral characters
    # weigh two units in both the distance and the threshold.
    threshold = max(2, math.ceil(len(needle_units) * 0.4))
    return best if best_score <= threshold else None


def _utf16_units(text: str) -> list[int]:
    encoded = text.encode("utf-16-be", "surrogatepass")
    return [int.from_bytes(encoded[i : i + 2], "big") for i in range(0, len(encoded), 2)]


def _levenshtein(left: list[int], right: list[int]) -> int:
    previous = list(range(len(right) + 1))
    for i, left_ch in enumerate(left, start=1):
        current = [i]
        for j, right_ch in enumerate(right, start=1):
            cost = 0 if left_ch == right_ch else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]


__all__ = [
    "Diagnostic",
    "SystemOnePromptsError",
    "SourceLocation",
    "diagnostic",
    "errors_of",
    "format_diagnostic",
    "format_location",
    "has_errors",
    "nearest_match",
]
