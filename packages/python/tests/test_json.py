from __future__ import annotations

import json
import math
import subprocess
from collections import UserDict
from datetime import datetime

import pytest

from systemoneprompts.json_values import (
    canonical_json,
    is_json_value,
    is_plain_object,
    js_json_dumps,
    parse_json,
    type_name,
)


def test_plain_objects_exclude_subclasses_and_wrappers() -> None:
    class Example(dict):  # noqa: FURB189
        pass

    assert is_plain_object({"valid": True})
    assert not is_plain_object(Example({"valid": True}))
    assert not is_plain_object(UserDict({"valid": True}))
    assert not is_json_value({"value": datetime(2026, 1, 1)})


def test_canonical_json_preserves_special_keys() -> None:
    left = json.loads('{"z":0,"__proto__":{"value":1}}')
    right = json.loads('{"__proto__":{"value":2},"z":0}')
    assert json.loads(canonical_json(left)) == left
    assert canonical_json(left) != canonical_json(right)


def test_json_validation_rejects_cycles_and_allows_shared_values() -> None:
    obj: dict[str, object] = {}
    obj["self"] = obj
    array: list[object] = []
    array.append(array)
    assert not is_json_value(obj)
    assert not is_json_value(array)

    shared = {"nested": [None, True, 1]}
    assert is_json_value({"first": shared, "second": shared})
    assert is_json_value([shared, shared])


def test_python_only_values_are_rejected() -> None:
    assert not is_json_value((1, 2))
    assert not is_json_value({1: "a"})
    assert not is_json_value({b"a": 1})
    assert not is_json_value(float("nan"))
    assert not is_json_value(math.inf)
    assert type_name(True) == "boolean"
    assert type_name(1) == "number"
    assert type_name([1]) == "array"


def test_canonical_json_matches_javascript_number_spellings() -> None:
    vectors = [
        (0.0, "0"),
        (-0.0, "0"),
        (1.0, "1"),
        (1, "1"),
        (1e20, "100000000000000000000"),
        (1e21, "1e+21"),
        (1e-6, "0.000001"),
        (1e-7, "1e-7"),
        (-1.25, "-1.25"),
        (0.1 + 0.2, "0.30000000000000004"),
        (0.3, "0.3"),
        (1.0000000000000002, "1.0000000000000002"),
        (9007199254740993, "9007199254740992"),
    ]
    for value, expected in vectors:
        assert canonical_json(value) == expected, (value, canonical_json(value), expected)


def test_canonical_json_escapes_unpaired_surrogates() -> None:
    assert canonical_json("\ud800") == r'"\ud800"'
    encoded = canonical_json({"\ud800": "\udfff"})
    encoded.encode("utf-8")
    assert r"\ud800" in encoded
    assert r"\udfff" in encoded
    assert canonical_json("\ud83d\ude00") == canonical_json("😀")
    assert "\\u" not in canonical_json("\ud83d\ude00")


def test_canonical_json_sorts_keys_like_javascript() -> None:
    encoded = canonical_json({"b": 1, "a": 2, "A": 3})
    assert encoded == '{"A":3,"a":2,"b":1}'
    assert canonical_json({"10": 1, "2": 2}) == '{"2":2,"10":1}'
    assert canonical_json({"b": 1, "10": 2, "2": 3, "a": 4}) == '{"2":3,"10":2,"a":4,"b":1}'
    assert canonical_json({"4294967295": 2, "01": 1}) == '{"01":1,"4294967295":2}'
    assert canonical_json({"4294967294": 2, "01": 1}) == '{"4294967294":2,"01":1}'


def test_canonical_json_matches_node_json_stringify_when_available() -> None:
    node = subprocess.run(["node", "-v"], capture_output=True, text=True, check=False)
    if node.returncode != 0:
        pytest.skip("node is not available")
    payload = {"z": 1, "a": [1.0, -0.0, 1e21, 1e-7], "é": {"b": 2, "a": 1}}
    rendered = subprocess.run(
        [
            "node",
            "-e",
            "const v=JSON.parse(process.argv[1]); const sort=x=>Array.isArray(x)?x.map(sort):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,sort(x[k])])):x; process.stdout.write(JSON.stringify(sort(v)));",
            json.dumps(payload),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert canonical_json(payload) == rendered.stdout
    addition = subprocess.run(
        ["node", "-e", "process.stdout.write(JSON.stringify(0.1+0.2))"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert canonical_json(0.1 + 0.2) == addition.stdout
    huge = subprocess.run(
        ["node", "-e", "process.stdout.write(JSON.stringify(9007199254740993))"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert canonical_json(9007199254740993) == huge.stdout
    surrogate = subprocess.run(
        ["node", "-e", r"process.stdout.write(JSON.stringify('\uD800'))"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert canonical_json("\ud800") == surrogate.stdout
    assert canonical_json({"\ud800": 1}).encode("utf-8")
    pair = subprocess.run(
        ["node", "-e", r"process.stdout.write(JSON.stringify('\uD83D\uDE00'))"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert canonical_json("\ud83d\ude00") == pair.stdout
    keys = subprocess.run(
        ["node", "-e", 'process.stdout.write(JSON.stringify(Object.fromEntries(["10","2"].sort().map(k=>[k,1]))))'],
        capture_output=True,
        text=True,
        check=True,
    )
    assert canonical_json({"10": 1, "2": 1}) == keys.stdout


def test_parse_json_rejects_nonstandard_constants() -> None:
    for text in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(json.JSONDecodeError):
            parse_json(text)
    assert parse_json("null") is None
    assert parse_json("9007199254740993") == 9007199254740992
    assert canonical_json(parse_json("1e400")) == "null"


def test_huge_integer_literals_are_infinity_like_javascript() -> None:
    # `JSON.parse("1" + "0".repeat(400))` is `Infinity`; `JSON.stringify` renders `null`.
    assert parse_json("1" + "0" * 309) == math.inf
    assert parse_json("[-1" + "0" * 400 + "]") == [-math.inf]
    assert parse_json("1" + "0" * 5000) == math.inf  # beyond CPython's int digit limit
    assert canonical_json(parse_json("1" + "0" * 400)) == "null"
    assert canonical_json(10**400) == "null"
    assert is_json_value(10**400) is False
    assert js_json_dumps({"n": 10**400}) == '{"n":null}'


def test_only_ascii_digits_are_array_indices() -> None:
    # `²` and `٣` pass `str.isdigit()` but are ordinary string keys in JavaScript.
    assert canonical_json(parse_json('{"²":1}')) == '{"²":1}'
    assert canonical_json(parse_json('{"٣":1,"1":2,"a":3}')) == '{"1":2,"a":3,"٣":1}'
    assert canonical_json(parse_json('{"１":1,"0":2}')) == '{"0":2,"１":1}'


def test_js_json_dumps_matches_json_stringify() -> None:
    assert js_json_dumps({"b": 1.0, "a": [2.5, -0.0, 1e-7], "é": "ü"}) == '{"b":1,"a":[2.5,0,1e-7],"é":"ü"}'
    assert js_json_dumps({"10": 1, "2": 1, "x": 1}) == '{"2":1,"10":1,"x":1}'
    lone = js_json_dumps({"s": "\ud800 ok \udfff"})
    assert lone == '{"s":"\\ud800 ok \\udfff"}'
    lone.encode("utf-8")  # must be transmittable
    assert js_json_dumps({"a": [1]}, indent=2) == '{\n  "a": [\n    1\n  ]\n}'
    assert js_json_dumps({"n": math.nan}) == '{"n":null}'
