from __future__ import annotations

from helpers import fixture
from systemoneprompts import check_definition, parse_definition
from systemoneprompts.model import DEFAULT_MODEL, read_env_model, resolve_model


def test_defaults_to_jev_latest() -> None:
    assert resolve_model() == "jev-latest"
    assert DEFAULT_MODEL == "jev-latest"


def test_later_non_empty_candidates_win() -> None:
    assert resolve_model("jev-latest", "jev-2026-06") == "jev-2026-06"
    assert resolve_model(None, "from-toml", "from-call") == "from-call"
    assert resolve_model("from-env", "from-toml") == "from-toml"


def test_read_env_model_blank_fallback() -> None:
    assert read_env_model({"TYPESAFE_MODEL": "  ", "TYPESAFE_DEFAULT_MODEL": "jev-default"}) == "jev-default"
    assert (
        read_env_model({"TYPESAFE_MODEL": "jev-explicit", "TYPESAFE_DEFAULT_MODEL": "jev-default"})
        == "jev-explicit"
    )


def test_omitted_model_stays_none() -> None:
    definition = parse_definition(fixture("golden/noul-string.toml"))
    assert definition.model is None


def test_empty_model_is_an_error() -> None:
    definition = parse_definition(fixture("errors/empty-model.toml"), filename="empty-model.toml")
    error = next(item for item in check_definition(definition) if item.code == "model-string")
    assert error.severity == "error"
    assert "non-empty string" in error.message
