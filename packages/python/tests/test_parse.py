from __future__ import annotations

from pathlib import Path

import pytest

from helpers import fixture, fixture_path
from systemoneprompts import check_definition, parse_definition


def test_golden_native_questions_round_trip() -> None:
    for name in ("triage.toml", "noul-string.toml", "choice-strings.toml", "score-strings.toml"):
        source = fixture(f"golden/{name}")
        definition = parse_definition(source, filename=name)
        errors = [item for item in check_definition(definition) if item.severity == "error"]
        assert errors == [], errors
        for question in definition.questions.values():
            assert question["type"] in {"noul", "choice", "score"}


def test_error_fixtures_produce_expected_codes() -> None:
    expected = {
        "backtick-typo.toml": "unguaranteed-backtick",
        "collision.toml": "id-collision",
        "cycle.toml": "cycle",
        "empty-model.toml": "model-string",
        "noul-confidence.toml": "noul-confidence",
        "score-as-boolean.toml": "non-boolean-ref",
        "unknown-option.toml": "unknown-option",
        "unknown-table.toml": "unknown-table",
    }
    for name, code in expected.items():
        definition = parse_definition(fixture(f"errors/{name}"), filename=name)
        diagnostics = check_definition(definition)
        assert any(item.code == code for item in diagnostics), (name, [item.code for item in diagnostics])


def test_toml_syntax_error_has_location() -> None:
    try:
        parse_definition("oops = [\n", filename="broken.toml")
    except Exception as error:
        assert "broken.toml" in str(error)
        assert error.diagnostics[0].line == 1  # type: ignore[attr-defined]
    else:
        raise AssertionError("expected TOML syntax error")


def test_extra_question_fields_are_reported_but_may_keep_the_question() -> None:
    definition = parse_definition(
        """
[questions.q]
type = "noul"
bonus = 1
"""
    )
    assert "q" in definition.questions
    assert any(item.code == "unknown-question-field" for item in definition.diagnostics)


def test_fixture_paths_exist() -> None:
    assert fixture_path("golden/triage.toml").exists()


def test_messages_render_values_like_javascript() -> None:
    definition = parse_definition(
        '[requires]\nq = true\ns = ["string"]\n[questions.a]\ntype = 1.0\n[questions.b]\ntype = ["noul"]\n[questions.c]\ntype = { a = 1 }\n'
    )
    messages = [item.message for item in definition.diagnostics]
    assert "[requires] `q` has unknown type `true`" in messages
    assert "[requires] `s` has unknown type `string`" in messages
    assert "question `a` has invalid type `1`" in messages
    assert "question `b` has invalid type `noul`" in messages
    assert "question `c` has invalid type `[object Object]`" in messages


def test_integer_like_ids_follow_javascript_enumeration_order() -> None:
    # JavaScript objects list array-index keys first in numeric order.
    definition = parse_definition(
        '[questions.topic]\ntype = "choice"\n[questions.topic.criteria]\n"10" = "ten"\n"9" = "nine"\nzeta = "z"\n"0" = "zero"\n"01" = "oh-one"\n[questions."42"]\ntype = "noul"\n[questions."7"]\ntype = "noul"\n'
    )
    assert list(definition.questions) == ["7", "42", "topic"]
    assert list(definition.questions["topic"]["criteria"]) == ["0", "9", "10", "zeta", "01"]


def test_duplicate_cycle_edges_report_each_back_edge() -> None:
    definition = parse_definition('[factors]\ns = { all = ["s", "s"] }\n')
    cycles = [item for item in check_definition(definition) if item.code == "cycle"]
    assert [item.message for item in cycles] == ["cycle: s → s", "cycle: s → s"]


def test_hints_measure_typos_in_utf16_code_units() -> None:
    # `quest😀i` is 8 UTF-16 units away by 3 edits from `questions` in JavaScript.
    definition = parse_definition('["quest😀i"]\nx = 1\n')
    unknown = next(item for item in definition.diagnostics if item.code == "unknown-table")
    assert unknown.hint == "did you mean [questions]?"


def test_integers_beyond_javascript_safe_range_are_toml_syntax_errors() -> None:
    from systemoneprompts import parse_definition
    from systemoneprompts.diagnostics import SystemOnePromptsError

    # smol-toml throws "integer value cannot be represented losslessly" for |n| > 2**53 - 1.
    cases = {
        '[questions.a]\ntype = 9007199254740993\n': (2, 8),
        '[questions.a]\ntype = "noul"\n[factors.f]\nnoul = "a"\nat_least = 9007199254740993\n': (5, 12),
        '[questions.a]\ntype = "noul"\ninstructions = { n = [1, 0x20000000000000] }\n': (3, 26),
        '[questions.a]\ntype = "noul"\ninstructions = { n = -9_007_199_254_740_993 }\n': (3, 22),
    }
    for source, (line, column) in cases.items():
        with pytest.raises(SystemOnePromptsError) as caught:
            parse_definition(source)
        [error] = caught.value.diagnostics
        assert error.code == "toml-syntax"
        assert error.message == "integer value cannot be represented losslessly"
        assert (error.line, error.column) == (line, column)
    # The boundary itself is fine; floats are never rejected at the TOML layer.
    definition = parse_definition('[questions.a]\ntype = "noul"\ninstructions = { n = [9007199254740991] }\n')
    assert definition.questions["a"]["instructions"]["n"] == [9007199254740991]
    definition = parse_definition('[questions.a]\ntype = "noul"\ninstructions = { n = 1e400 }\n')
    assert [item.code for item in definition.diagnostics] == ["invalid-instructions"]


def test_load_definition_preserves_bare_carriage_returns(tmp_path: Path) -> None:
    from systemoneprompts import load_definition
    from systemoneprompts.diagnostics import SystemOnePromptsError

    path = tmp_path / "cr.toml"
    path.write_bytes(b'[questions.a]\rtype = "noul"\n')
    with pytest.raises(SystemOnePromptsError) as caught:
        load_definition(str(path))
    assert caught.value.diagnostics[0].code == "toml-syntax"
    assert caught.value.diagnostics[0].line == 1


def test_load_definition_replaces_invalid_utf8(tmp_path: Path) -> None:
    from systemoneprompts import load_definition

    path = tmp_path / "latin1.toml"
    path.write_bytes(b'[questions.a]\ntype = "noul"\ninstructions = "caf\xe9"\n')
    definition = load_definition(str(path))
    assert definition.questions["a"]["instructions"] == "caf\ufffd"


def test_data_preserves_arbitrary_json_compatible_structure() -> None:
    definition = parse_definition(
        '''
[questions.topic]
type = "noul"

[data]
"__proto__" = { "display.name" = "Delivery", nested = [true, 2.5, { "0" = "zero" }] }
items = [
  { id = "cost", labels = ["price", "charge"] },
  { id = "timing", copy = """Delivery\ntime""" },
]
''',
        filename="delivery.toml",
    )
    assert definition.diagnostics == []
    assert definition.data == {
        "__proto__": {
            "display.name": "Delivery",
            "nested": [True, 2.5, {"0": "zero"}],
        },
        "items": [
            {"id": "cost", "labels": ["price", "charge"]},
            {"id": "timing", "copy": "Delivery\ntime"},
        ],
    }


def test_data_defaults_to_empty_and_is_not_an_unknown_table() -> None:
    definition = parse_definition('[questions.q]\ntype = "noul"\n')
    assert definition.data == {}
    assert not any(item.code == "unknown-table" for item in definition.diagnostics)


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ('data = "not a table"\n[questions.q]\ntype = "noul"\n', "data-type"),
        ('data = []\n[questions.q]\ntype = "noul"\n', "data-type"),
        (
            'data = { created = 2026-09-20T12:00:00Z }\n[questions.q]\ntype = "noul"\n',
            "data-json",
        ),
        ('[data]\nvalue = inf\n[questions.q]\ntype = "noul"\n', "data-json"),
    ],
)
def test_invalid_data_values_are_diagnosed_and_omitted(source: str, code: str) -> None:
    definition = parse_definition(source, filename="invalid-data.toml")
    assert definition.data == {}
    errors = [item for item in definition.diagnostics if item.code == code]
    assert len(errors) == 1
    assert errors[0].severity == "error"
    assert errors[0].filename == "invalid-data.toml"
