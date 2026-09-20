import importlib.util
import json
from pathlib import Path

import pytest

from systemoneprompts import (
    SystemOnePromptsError,
    check_definition,
    create_factor_evaluator,
    create_state_assert,
    parse_definition,
    render_definition,
    resolve_model,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "conformance" / "v1" / "cases" / "basic"


def test_parse_and_evaluate_conformance_seed() -> None:
    definition = parse_definition((CORPUS / "definition.toml").read_text())
    assert not [item for item in check_definition(definition) if item.severity == "error"]
    state = json.loads((CORPUS / "state.json").read_text())
    create_state_assert(definition.requires)(state)
    answers = json.loads((CORPUS / "answers.json").read_text())
    expected = json.loads((CORPUS / "expected.json").read_text())
    assert expected["state_valid"] is True
    assert create_factor_evaluator(definition.factor_definitions)(answers) == expected["factors"]


def test_missing_required_state_is_an_error() -> None:
    assertion = create_state_assert({"ticket.message": "string"})
    with pytest.raises(SystemOnePromptsError, match="ticket.message"):
        assertion({"ticket": {}})


def test_unknown_factor_reference_is_reported() -> None:
    definition = parse_definition(
        """
[questions.a]
type = "noul"

[factors]
bad = { ref = "missing", noul = { gte = 0.5 } }
"""
    )
    assert any(item.code == "unknown-ref" for item in check_definition(definition))


def test_generated_module_is_importable(tmp_path: Path) -> None:
    from systemoneprompts import generate

    definition = parse_definition((CORPUS / "definition.toml").read_text())
    output = generate(definition, tmp_path / "generated.py")
    spec = importlib.util.spec_from_file_location("generated", output)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.evaluate_factors({"topic": {"choice": "billing"}, "urgent": {"noul": 0.8}})[
        "route"
    ]


def test_requirement_container_conflict_is_reported() -> None:
    definition = parse_definition(
        """
[requires]
"ticket.message" = "string"
"ticket[0].message" = "string"

[questions]
"q" = { type = "noul" }
"""
    )
    assert any(item.code == "require-conflict" for item in check_definition(definition))


def test_factor_primitive_mismatch_is_reported() -> None:
    definition = parse_definition(
        """
[questions]
topic = { type = "choice", criteria = { billing = "billing" } }

[factors]
bad = { ref = "topic", noul = { gte = 0.5 } }
"""
    )
    assert any(item.code == "noul-on-non-noul" for item in check_definition(definition))


def test_render_is_deterministic_and_does_not_write(tmp_path: Path) -> None:
    definition = parse_definition((CORPUS / "definition.toml").read_text())
    first = render_definition(definition)
    second = render_definition(definition)
    assert first == second
    assert not (tmp_path / ".systemoneprompts-generated-preview.py").exists()


def test_repeated_json_containers_are_valid_but_cycles_are_not() -> None:
    from systemoneprompts.json_values import is_json_value

    shared: dict[str, object] = {"value": 1}
    assert is_json_value([shared, shared])
    shared["self"] = shared
    assert not is_json_value(shared)


def test_model_precedence_ignores_blank_values() -> None:
    assert resolve_model("env-model", "definition-model", "call-model") == "call-model"
    assert resolve_model("env-model", "definition-model", " ") == "definition-model"
    assert resolve_model(" ", None, None) == "jev-latest"


def test_null_is_not_missing_for_required_string() -> None:
    assertion = create_state_assert({"ticket.message": "string"})
    with pytest.raises(SystemOnePromptsError, match="got null"):
        assertion({"ticket": {"message": None}})
    with pytest.raises(SystemOnePromptsError, match="got undefined"):
        assertion({"ticket": {}})


def test_assertions_do_not_mutate_state() -> None:
    state = {"ticket": {"message": "hi"}}
    create_state_assert({"ticket.message": "string"})(state)
    assert state == {"ticket": {"message": "hi"}}


def test_wildcard_requires_every_element() -> None:
    from systemoneprompts.requirements import ALL_INDEX, parse_path

    assert parse_path("[]") is None
    assert parse_path("messages[].text") == ["messages", ALL_INDEX, "text"]
    assert parse_path("messages[-1].text") == ["messages", -1, "text"]
    assert parse_path("items[-4294967294]") is not None
    assert parse_path("items[-4294967295]") is None

    last = create_state_assert({"messages[-1].text": "string"})
    last({"messages": [{"text": "first"}, {"text": "last"}]})
    with pytest.raises(SystemOnePromptsError, match=r"messages\[-1\]\.text"):
        last({"messages": []})

    assertion = create_state_assert({"messages[].text": "string"})
    assertion({"messages": []})
    assertion({"messages": [{"text": "a"}, {"text": "b"}]})
    with pytest.raises(
        SystemOnePromptsError, match=r"messages\[\]\.text: expected string, got number"
    ):
        assertion({"messages": [{"text": "a"}, {"text": 1}]})
    with pytest.raises(SystemOnePromptsError, match="messages: expected array, got object"):
        assertion({"messages": {"text": "a"}})
    with pytest.raises(SystemOnePromptsError, match="messages: expected array, got string"):
        assertion({"messages": "bad"})
    with pytest.raises(SystemOnePromptsError, match="messages: expected array, got undefined"):
        assertion({})
    nested = create_state_assert({"grid[][]": "number"})
    nested({"grid": [[1, 2], []]})
    with pytest.raises(SystemOnePromptsError, match=r"grid\[\]: expected array, got number"):
        nested({"grid": [[1], 2]})

    mixed = parse_definition(
        """
[requires]
"messages[].text" = "string"
"messages[0].id" = "string"

[questions]
"q" = { type = "noul" }
"""
    )
    assert [item for item in check_definition(mixed) if item.code == "require-conflict"] == []

    object_vs_all = parse_definition(
        """
[requires]
as_object = "object"
"as_object[]" = "string"

[questions]
"q" = { type = "noul" }
"""
    )
    assert any(item.code == "require-conflict" for item in check_definition(object_vs_all))

    descendant = parse_definition(
        """
[requires]
"messages[].x" = "string"
"messages[0].x.y" = "number"

[questions]
"q" = { type = "noul" }
"""
    )
    conflicts = [item.message for item in check_definition(descendant) if item.code == "require-conflict"]
    assert conflicts == [
        "[requires] `messages[].x` is `string` but `messages[0].x.y` requires it to be a container"
    ]

    covered = parse_definition(
        """
[requires]
"messages[].text" = "string"

[questions.q]
type = "noul"
instructions = "Inspect `messages[0].text`."
"""
    )
    assert [
        item for item in check_definition(covered) if item.code == "unguaranteed-backtick"
    ] == []
    covered_last = parse_definition(
        """
[requires]
"messages[].text" = "string"

[questions.q]
type = "noul"
instructions = "Inspect `messages[-1].text`."
"""
    )
    assert [
        item for item in check_definition(covered_last) if item.code == "unguaranteed-backtick"
    ] == []

    not_covered = parse_definition(
        """
[requires]
"messages[0].text" = "string"

[questions.q]
type = "noul"
instructions = "Inspect `messages[].text`."
"""
    )
    assert any(item.code == "unguaranteed-backtick" for item in check_definition(not_covered))
