"""Best-effort TOML source locations for diagnostics.

The index locates already-parsed keys; it is not a second TOML parser. Positions are
omitted rather than invented when a match is unavailable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .diagnostics import SourceLocation

TABLE_RE = re.compile(r"^(\s*)\[(\[?)(.*?)(\]?)](?:\s*#.*)?$")
KEY_RE = re.compile(r"""^(\s*)((?:"(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_-]+))\s*=""")


@dataclass
class SourceIndex:
    filename: str | None = None
    tables: dict[str, SourceLocation] = field(default_factory=dict)
    keys: dict[str, SourceLocation] = field(default_factory=dict)
    table_paths: dict[str, SourceLocation] = field(default_factory=dict)
    key_paths: dict[str, SourceLocation] = field(default_factory=dict)


EMPTY_INDEX = SourceIndex()
_LINE_BREAK = re.compile(r"\r?\n")


def split_lines(text: str) -> list[str]:
    """Split like the TypeScript `text.split(/\\r?\\n/)`.

    `str.splitlines()` also breaks on U+2028/U+2029/U+0085, which TOML allows inside
    strings, and would shift every following line number.
    """
    return _LINE_BREAK.split(text)


def index_source(text: str, filename: str | None = None) -> SourceIndex:
    tables: dict[str, SourceLocation] = {}
    keys: dict[str, SourceLocation] = {}
    table_paths: dict[str, SourceLocation] = {}
    key_paths: dict[str, SourceLocation] = {}
    current_table = ""
    current_table_path: list[str] = []

    for index, line in enumerate(split_lines(text)):
        trimmed = line.strip()
        if trimmed == "" or trimmed.startswith("#"):
            continue
        table_match = TABLE_RE.match(line)
        if table_match:
            raw_path = (table_match.group(3) or "").strip()
            segments = parse_toml_path(raw_path)
            path = normalize_table_path(segments) if segments is not None else raw_path
            location = SourceLocation(filename, index + 1, len(table_match.group(1) or "") + 1)
            tables.setdefault(path, location)
            if segments is not None:
                table_paths.setdefault(path_key(segments), location)
            current_table = path
            current_table_path = segments or []
            continue
        key_match = KEY_RE.match(line)
        if key_match:
            raw_key = key_match.group(2) or ""
            key = unquote_toml_key(raw_key)
            qualified = f"{current_table}.{key}" if current_table else key
            location = SourceLocation(filename, index + 1, len(key_match.group(1) or "") + 1)
            keys.setdefault(qualified, location)
            keys.setdefault(key, location)
            qualified_path = [*current_table_path, key]
            key_paths.setdefault(path_key(qualified_path), location)
            key_paths.setdefault(path_key([key]), location)

    return SourceIndex(filename, tables, keys, table_paths, key_paths)


def locate(
    index: SourceIndex,
    *,
    table: str | list[str] | tuple[str, ...] | None = None,
    key: str | None = None,
    section: str | None = None,
) -> SourceLocation:
    filename = index.filename
    if section and key:
        scoped_table = index.table_paths.get(path_key([section, key]))
        if scoped_table:
            return scoped_table
        nested_table = find_nested_table(index.table_paths, [section, key])
        if nested_table:
            return nested_table
        scoped = index.key_paths.get(path_key([section, key]))
        if scoped:
            return scoped
        found = index.keys.get(f"{section}.{key}")
        if found:
            return found
    if table is not None:
        segments = parse_toml_path(table) if isinstance(table, str) else list(table)
        found = index.table_paths.get(path_key(segments)) if segments is not None else None
        if found:
            return found
        nested = find_nested_table(index.table_paths, segments) if segments is not None else None
        if nested:
            return nested
        legacy = table if isinstance(table, str) else ".".join(table)
        fallback = index.tables.get(legacy)
        if fallback:
            return fallback
    if key:
        found = index.key_paths.get(path_key([key]))
        if found:
            return found
        fallback = index.keys.get(key)
        if fallback:
            return fallback
    if section:
        found = index.table_paths.get(path_key([section]))
        if found:
            return found
        fallback = index.tables.get(section)
        if fallback:
            return fallback
    return SourceLocation(filename)


def normalize_table_path(segments: list[str]) -> str:
    return ".".join(segments)


def path_key(segments: list[str]) -> str:
    return json.dumps(segments, ensure_ascii=False, separators=(",", ":"))


def find_nested_table(
    table_paths: dict[str, SourceLocation], segments: list[str]
) -> SourceLocation | None:
    for serialized, location in table_paths.items():
        try:
            candidate = json.loads(serialized)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(candidate, list)
            and len(candidate) > len(segments)
            and all(candidate[index] == item for index, item in enumerate(segments))
        ):
            return location
    return None


def parse_toml_path(raw: str) -> list[str] | None:
    segments: list[str] = []
    cursor = 0
    length = len(raw)
    while cursor < length:
        while cursor < length and raw[cursor] == " ":
            cursor += 1
        if cursor >= length:
            break
        if raw[cursor] in {'"', "'"}:
            quote = raw[cursor]
            start = cursor
            cursor += 1
            escaped = False
            while cursor < length:
                char = raw[cursor]
                cursor += 1
                if escaped:
                    escaped = False
                elif quote == '"' and char == "\\":
                    escaped = True
                elif char == quote:
                    break
            token = raw[start:cursor]
            if not token.endswith(quote):
                return None
            segments.append(unquote_toml_key(token))
        else:
            start = cursor
            while cursor < length and raw[cursor] != ".":
                cursor += 1
            token = raw[start:cursor].strip()
            if not token:
                return None
            segments.append(token)
        while cursor < length and raw[cursor] == " ":
            cursor += 1
        if cursor >= length:
            break
        if raw[cursor] != ".":
            return None
        cursor += 1
    return segments or None


def unquote_toml_key(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw[1:-1]
        return parsed if isinstance(parsed, str) else raw[1:-1]
    if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        return raw[1:-1]
    return raw


__all__ = [
    "EMPTY_INDEX",
    "SourceIndex",
    "index_source",
    "locate",
    "parse_toml_path",
    "split_lines",
]
