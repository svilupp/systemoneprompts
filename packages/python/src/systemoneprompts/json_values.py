"""JSON-value helpers with JavaScript-compatible canonical encoding."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any


def is_plain_object(value: Any) -> bool:
    """True for a JSON object: a `dict` instance, not a subclass or mapping wrapper."""
    return type(value) is dict


def is_json_value(value: Any, *, _seen: set[int] | None = None) -> bool:
    seen = _seen if _seen is not None else set()
    if value is None or isinstance(value, str) or type(value) is bool:
        return True
    if type(value) is int:
        # Integers beyond IEEE-754 range are `Infinity` in JavaScript and not JSON values.
        return _int_to_float(value) is not None
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        identity = id(value)
        if identity in seen:
            return False
        seen.add(identity)
        try:
            return all(is_json_value(item, _seen=seen) for item in value)
        finally:
            seen.remove(identity)
    if is_plain_object(value):
        identity = id(value)
        if identity in seen:
            return False
        seen.add(identity)
        try:
            return all(
                isinstance(key, str) and is_json_value(item, _seen=seen)
                for key, item in value.items()
            )
        finally:
            seen.remove(identity)
    return False


def is_entry_type(value: Any) -> bool:
    """Instructions and criteria entries: null, string, or JSON object/array."""
    if value is None or isinstance(value, str):
        return True
    if type(value) is list or is_plain_object(value):
        return is_json_value(value)
    return False


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if isinstance(value, str):
        return "string"
    if type(value) is int or type(value) is float:
        return "number"
    if type(value) is list:
        return "array"
    if is_plain_object(value) or isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def canonical_json(value: Any) -> str:
    """JSON with recursively sorted keys and JavaScript `JSON.stringify` number spellings."""
    return _stringify(_sort_keys(value))


def parse_json(text: str) -> Any:
    """`JSON.parse`: reject `NaN` / `Infinity` tokens and apply IEEE-754 number values.

    Integer literals too long for a float (`1e309` and beyond, or past CPython's digit
    limit) become `inf`, as `JSON.parse` yields `Infinity`; `canonical_json` then
    renders them as `null` like `JSON.stringify`.
    """
    return _adapt_js_json(
        json.loads(text, parse_int=_parse_js_int, parse_constant=_reject_json_constant)
    )


def _parse_js_int(literal: str) -> int | float:
    if len(literal) > 308:
        return float(literal)
    return int(literal)


def _int_to_float(value: int) -> float | None:
    try:
        as_float = float(value)
    except OverflowError:
        return None
    return as_float if math.isfinite(as_float) else None


def _adapt_js_json(value: Any) -> Any:
    if type(value) is int:
        as_float = _int_to_float(value)
        if as_float is None:
            return math.inf if value > 0 else -math.inf
        if value != int(as_float):
            return as_float
        return value
    if type(value) is list:
        return [_adapt_js_json(item) for item in value]
    if is_plain_object(value):
        return {key: _adapt_js_json(item) for key, item in value.items()}
    return value


def _reject_json_constant(name: str) -> Any:
    raise json.JSONDecodeError(f"{name} is not valid JSON", name, 0)


def js_string(value: Any) -> str:
    """JavaScript `String(value)` for values that appear in messages and labels."""
    if type(value) is bool:
        return "true" if value else "false"
    if value is None:
        return "null"
    if type(value) is float:
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return _js_number(value)
    if type(value) is int:
        return str(value)
    if isinstance(value, str):
        return value
    if type(value) is list:
        return ",".join("" if item is None else js_string(item) for item in value)
    if isinstance(value, Mapping):
        return "[object Object]"
    return str(value)


def js_json_value(value: Any) -> Any:
    """Prepare a value for `json.dumps` so the text matches `JSON.stringify`.

    Mapping keys follow JavaScript enumeration order, integer-valued floats become
    integers (`1` rather than `1.0`), and non-finite numbers (including integers
    beyond IEEE-754 range) become `null`.
    """
    if type(value) is float:
        if not math.isfinite(value):
            return None
        if value.is_integer() and abs(value) < 1e21:
            return int(value)
        return value
    if type(value) is int:
        return None if _int_to_float(value) is None else value
    if type(value) is list or type(value) is tuple:
        return [js_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {key: js_json_value(value[key]) for key in _js_enumerate_keys(list(value))}
    return value


def js_json_dumps(value: Any, *, indent: int | None = None) -> str:
    """`JSON.stringify(value)` / `JSON.stringify(value, null, indent)` as text.

    JavaScript key enumeration order, number spellings (`1`, `1e-7`), literal
    non-ASCII, and `\\uXXXX` escapes for lone surrogates so the text is UTF-8 encodable.
    """
    prepared = js_json_value(value)
    if indent is None:
        return _stringify(prepared)
    return _stringify_pretty(prepared, " " * indent, "")


def _stringify_pretty(value: Any, step: str, current: str) -> str:
    inner = current + step
    if type(value) is list:
        if not value:
            return "[]"
        items = ",\n".join(inner + _stringify_pretty(item, step, inner) for item in value)
        return "[\n" + items + "\n" + current + "]"
    if is_plain_object(value):
        if not value:
            return "{}"
        items = ",\n".join(
            inner + _js_string_literal(key) + ": " + _stringify_pretty(item, step, inner)
            for key, item in value.items()
        )
        return "{\n" + items + "\n" + current + "}"
    return _stringify(value)


def js_key_order(value: Any) -> Any:
    """Reorder mapping keys the way a JavaScript object enumerates them.

    TOML parsers in JavaScript produce plain objects, so integer-like keys (`"0"`,
    `"10"`) enumerate first in numeric order and the rest keep insertion order.
    Applied to parsed TOML so question, criteria, and factor order match the
    reference implementation.
    """
    if type(value) is list:
        return [js_key_order(item) for item in value]
    if is_plain_object(value):
        return {key: js_key_order(value[key]) for key in _js_enumerate_keys(list(value))}
    return value


def _js_key_sort(keys: list[str]) -> list[str]:
    # JS `Object.keys(obj).sort()` compares UTF-16 code units. UTF-16-BE byte
    # order matches that numeric order; UTF-16-LE does not.
    return sorted(keys, key=lambda key: key.encode("utf-16-be", "surrogatepass"))


def _is_array_index(key: str) -> bool:
    # Canonical numeric index: ToString(n) for integer n in [0, 2**32 - 1). Only ASCII
    # digits qualify; `str.isdigit()` also accepts `²` or `٣`, which JavaScript does not.
    if key == "0":
        return True
    if not key.isascii() or not key.isdigit() or key[0] == "0":
        return False
    return int(key) < 2**32 - 1


def _js_enumerate_keys(lex_sorted: list[str]) -> list[str]:
    # After `Object.fromEntries(sorted keys)`, JSON.stringify enumerates integer
    # indices in numeric order, then remaining keys in insertion order.
    indices = [key for key in lex_sorted if _is_array_index(key)]
    rest = [key for key in lex_sorted if not _is_array_index(key)]
    indices.sort(key=lambda key: int(key))
    return indices + rest


def _sort_keys(value: Any) -> Any:
    if type(value) is list:
        return [_sort_keys(item) for item in value]
    if is_plain_object(value):
        ordered = _js_enumerate_keys(_js_key_sort(list(value)))
        return {key: _sort_keys(value[key]) for key in ordered}
    return value


def _stringify(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _js_string_literal(value)
    if type(value) is int:
        as_float = _int_to_float(value)
        return "null" if as_float is None else _js_number(as_float)
    if type(value) is float:
        if not math.isfinite(value):
            return "null"
        return _js_number(value)
    if type(value) is list:
        return "[" + ",".join(_stringify(item) for item in value) + "]"
    if is_plain_object(value):
        parts = [
            _js_string_literal(key) + ":" + _stringify(item)
            for key, item in value.items()
        ]
        return "{" + ",".join(parts) + "}"
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


def _js_string_literal(value: str) -> str:
    """`JSON.stringify` of a string: unpaired surrogates escaped, pairs as characters."""
    if not any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        return json.dumps(value, ensure_ascii=False)
    escaped: list[str] = []
    index = 0
    length = len(value)
    while index < length:
        code = ord(value[index])
        if 0xD800 <= code <= 0xDBFF and index + 1 < length:
            low = ord(value[index + 1])
            if 0xDC00 <= low <= 0xDFFF:
                scalar = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                escaped.append(json.dumps(chr(scalar), ensure_ascii=False)[1:-1])
                index += 2
                continue
        if 0xD800 <= code <= 0xDFFF:
            escaped.append(f"\\u{code:04x}")
        else:
            escaped.append(json.dumps(value[index], ensure_ascii=False)[1:-1])
        index += 1
    return '"' + "".join(escaped) + '"'


def _js_number(value: float) -> str:
    """ECMA-262 `ToString` as used by `JSON.stringify`."""
    if not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    digits, exponent = _unique_scientific(abs(value))
    if exponent >= 21 or exponent < -6:
        mantissa = digits if len(digits) == 1 else f"{digits[0]}.{digits[1:]}"
        return f"{sign}{mantissa}e{'+' if exponent >= 0 else ''}{exponent}"
    if exponent >= 0:
        padded = digits.ljust(exponent + 1, "0")
        integer_part = padded[: exponent + 1]
        fraction_part = padded[exponent + 1 :].rstrip("0")
        body = integer_part if not fraction_part else f"{integer_part}.{fraction_part}"
        return sign + body
    zeros = -exponent - 1
    return f"{sign}0.{'0' * zeros}{digits}"


def _unique_scientific(magnitude: float) -> tuple[str, int]:
    """Return significand digits and the exponent of the first digit."""
    return _digits_and_exponent(repr(magnitude))


def _digits_and_exponent(text: str) -> tuple[str, int]:
    if text.endswith(".0"):
        text = text[:-2]
    if "e" in text or "E" in text:
        mantissa, exponent_text = text.lower().split("e")
        base = int(exponent_text)
        if "." in mantissa:
            whole, fraction = mantissa.split(".", 1)
        else:
            whole, fraction = mantissa, ""
        if whole in {"", "0"}:
            stripped = fraction.lstrip("0") or "0"
            leading = len(fraction) - len(stripped) if stripped != "0" else len(fraction)
            return stripped, base - leading - 1
        digits = (whole.lstrip("0") + fraction).rstrip("0") or "0"
        return digits, base + len(whole.lstrip("0")) - 1
    if "." in text:
        whole, fraction = text.split(".", 1)
    else:
        whole, fraction = text, ""
    if whole in {"", "0"}:
        stripped = fraction.lstrip("0") or "0"
        if stripped == "0":
            return "0", 0
        leading = len(fraction) - len(stripped)
        return stripped, -leading - 1
    digits = (whole.lstrip("0") + fraction).rstrip("0") or "0"
    return digits, len(whole.lstrip("0")) - 1


__all__ = [
    "canonical_json",
    "is_entry_type",
    "is_json_value",
    "is_plain_object",
    "js_json_dumps",
    "js_json_value",
    "js_key_order",
    "js_string",
    "parse_json",
    "type_name",
]
