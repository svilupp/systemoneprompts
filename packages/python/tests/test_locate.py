from __future__ import annotations

from systemoneprompts import check_definition, parse_definition
from systemoneprompts.locate import index_source, locate


def test_locates_single_quoted_keys() -> None:
    index = index_source("[requires]\n'customer.id' = true\n", "definition.toml")
    location = locate(index, section="requires", key="customer.id")
    assert location.filename == "definition.toml"
    assert location.line == 2
    assert location.column == 1


def test_keeps_dotted_single_quoted_question_ids() -> None:
    index = index_source("[questions.'score.dotted']\ntype = \"score\"\n", "definition.toml")
    location = locate(index, table="questions.'score.dotted'")
    assert location.line == 1
    assert location.column == 1


def test_falls_back_to_nested_array_of_table() -> None:
    index = index_source('[[questions.score.criteria]]\nlabel = "Calm"\n', "definition.toml")
    location = locate(index, table="questions.score")
    assert location.line == 1
    assert location.column == 1


def test_does_not_invent_line_one_when_missing() -> None:
    index = index_source("title = \"x\"\n", "definition.toml")
    location = locate(index, table="missing")
    assert location.filename == "definition.toml"
    assert location.line is None


def test_nested_table_lookup_requires_matching_prefix() -> None:
    # A deeper table under a different section must not satisfy a factor lookup.
    source = (
        "[questions.topic]\ntype = \"choice\"\n[questions.topic.criteria]\nbilling = \"b\"\n"
        "\n[factors]\n\n[factors.route]\nref = \"topic\"\nchoice = \"billing\"\nbogus = 1\n"
    )
    index = index_source(source, "definition.toml")
    assert locate(index, section="factors", key="route").line == 8
    definition = parse_definition(source, filename="definition.toml")
    unknown = next(item for item in definition.diagnostics if item.code == "unknown-factor-field")
    assert unknown.line == 8


def test_line_numbers_ignore_unicode_line_separators() -> None:
    # `str.splitlines()` would treat U+2028 / U+0085 as line breaks; TOML and the
    # TypeScript locator do not.
    for separator in ("\u2028", "\u0085"):
        source = f'[questions.a]\ntype = "noul"\ninstructions = "one{separator}two"\n\n[factors]\nf = {{ ref = "missing", known = true }}\n'
        definition = parse_definition(source, filename="definition.toml")
        unknown = next(
            item
            for item in definition.diagnostics + check_definition(definition)
            if item.code == "unknown-ref"
        )
        assert unknown.line == 6


def test_nested_array_of_table_diagnostics_use_question_path() -> None:
    definition = parse_definition(
        "[[questions.'score.dotted'.criteria]]\nlabel = \"Calm\"\n",
        filename="definition.toml",
    )
    diagnostic = next(item for item in definition.diagnostics if item.code == "invalid-question-type")
    assert diagnostic.filename == "definition.toml"
    assert diagnostic.line == 1
    assert diagnostic.column == 1
