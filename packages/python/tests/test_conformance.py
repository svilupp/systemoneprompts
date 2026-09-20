from __future__ import annotations

import json
from pathlib import Path

import pytest

from systemoneprompts import (
    check_definition,
    create_factor_evaluator,
    create_state_assert,
    parse_definition,
)
from systemoneprompts.diagnostics import errors_of

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "conformance" / "v1"
SUPPORTED = {"parse", "assert_state", "evaluate_factors"}


def _operations(manifest: dict[str, object], case_id: str, case_dir: Path) -> list[str]:
    declared = manifest.get("operations")
    if isinstance(declared, dict) and case_id in declared:
        operations = declared[case_id]
        if not isinstance(operations, list) or not operations:
            raise AssertionError(f"case `{case_id}` declares no operations")
        unknown = [item for item in operations if item not in SUPPORTED]
        if unknown:
            raise AssertionError(f"unsupported operation(s) for `{case_id}`: {unknown}")
        return [str(item) for item in operations]
    operations = ["parse"]
    if (case_dir / "state.json").exists():
        operations.append("assert_state")
    if (case_dir / "answers.json").exists():
        operations.append("evaluate_factors")
    return operations


def _run_case(case_dir: Path, operations: list[str]) -> dict[str, object]:
    definition = parse_definition(
        (case_dir / "definition.toml").read_text(encoding="utf-8"),
        filename=str(case_dir / "definition.toml"),
    )
    diagnostics = check_definition(definition)
    errors = errors_of(diagnostics)
    if errors:
        raise RuntimeError("\n".join(item.message for item in errors))
    result: dict[str, object] = {}
    if "assert_state" in operations:
        state = json.loads((case_dir / "state.json").read_text(encoding="utf-8"))
        try:
            create_state_assert(definition.requires)(state)
            result["state_valid"] = True
        except Exception:
            result["state_valid"] = False
    if "evaluate_factors" in operations:
        answers = json.loads((case_dir / "answers.json").read_text(encoding="utf-8"))
        result["factors"] = create_factor_evaluator(definition.factor_definitions)(answers)
    return result


def _cases() -> list[str]:
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    case_ids = manifest.get("cases")
    if not isinstance(case_ids, list) or not case_ids:
        raise AssertionError("conformance manifest must declare at least one case")
    seen: set[str] = set()
    for case_id in case_ids:
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise AssertionError(f"invalid or duplicate conformance case id: {case_id!r}")
        seen.add(case_id)
        declared = manifest.get("operations")
        if isinstance(declared, dict) and case_id in declared:
            unknown = [item for item in declared[case_id] if item not in SUPPORTED]
            if unknown:
                raise AssertionError(f"unsupported operation(s) for `{case_id}`: {unknown}")
    return [str(case_id) for case_id in case_ids]


def test_manifest_rejects_duplicates_and_unknown_operations(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("test_conformance.CORPUS", tmp_path)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"version": "v1", "cases": ["a", "a"]}),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError):
        _cases()


@pytest.mark.parametrize("case_id", _cases())
def test_conformance_case(case_id: str) -> None:
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    seen: set[str] = set()
    assert case_id not in seen
    case_dir = CORPUS / "cases" / case_id
    expected_path = case_dir / "expected.json"
    assert (case_dir / "definition.toml").exists()
    assert expected_path.exists()
    operations = _operations(manifest, case_id, case_dir)
    actual = _run_case(case_dir, operations)
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert actual == expected


def test_conformance_data_is_preserved() -> None:
    definition = parse_definition(
        (CORPUS / "cases" / "basic" / "definition.toml").read_text(encoding="utf-8")
    )
    assert definition.data == {
        "labels": {"billing": "Billing", "orders": "Orders"},
        "variants": ["first", "second"],
        "nested": {"message": "Application-owned text stays outside the provider questions.\n"},
    }
