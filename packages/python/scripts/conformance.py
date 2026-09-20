#!/usr/bin/env python3
"""Run every declared offline v1 conformance case for the Python package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from systemoneprompts import (
    check_definition,
    create_factor_evaluator,
    create_state_assert,
    parse_definition,
)
from systemoneprompts.diagnostics import errors_of

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "conformance" / "v1"
SUPPORTED_OPERATIONS = {"parse", "assert_state", "evaluate_factors"}


def load_manifest() -> dict[str, Any]:
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    case_ids = manifest.get("cases")
    if not isinstance(case_ids, list) or not case_ids:
        raise RuntimeError("conformance manifest must declare at least one case")
    seen: set[str] = set()
    for case_id in case_ids:
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise RuntimeError(f"invalid or duplicate conformance case id: {case_id!r}")
        seen.add(case_id)
    return manifest


def operations_for(manifest: dict[str, Any], case_id: str, case_dir: Path) -> list[str]:
    declared = manifest.get("operations")
    if isinstance(declared, dict) and case_id in declared:
        operations = declared[case_id]
        if not isinstance(operations, list) or not operations:
            raise RuntimeError(f"case `{case_id}` declares no operations")
        unknown = [item for item in operations if item not in SUPPORTED_OPERATIONS]
        if unknown:
            raise RuntimeError(f"unsupported operation(s) for `{case_id}`: {unknown}")
        return [str(item) for item in operations]
    operations = ["parse"]
    if (case_dir / "state.json").exists():
        operations.append("assert_state")
    if (case_dir / "answers.json").exists():
        operations.append("evaluate_factors")
    return operations


def case_result(case_dir: Path, operations: list[str]) -> dict[str, Any]:
    definition = parse_definition(
        (case_dir / "definition.toml").read_text(encoding="utf-8"),
        filename=str(case_dir / "definition.toml"),
    )
    diagnostics = check_definition(definition)
    errors = errors_of(diagnostics)
    if errors:
        raise RuntimeError("\n".join(item.message for item in errors))

    result: dict[str, Any] = {}
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


def run_corpus() -> int:
    manifest = load_manifest()
    for case_id in manifest["cases"]:
        case_dir = CORPUS / "cases" / str(case_id)
        expected_path = case_dir / "expected.json"
        if not (case_dir / "definition.toml").exists() or not expected_path.exists():
            raise RuntimeError(f"case `{case_id}` is missing definition.toml or expected.json")
        operations = operations_for(manifest, str(case_id), case_dir)
        actual = case_result(case_dir, operations)
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        if actual != expected:
            raise RuntimeError(f"case `{case_id}` mismatch:\nexpected={expected!r}\nactual={actual!r}")
        print(f"conformance: {case_id} ({', '.join(operations)}) OK")
    return 0


def main() -> int:
    return run_corpus()


if __name__ == "__main__":
    raise SystemExit(main())
