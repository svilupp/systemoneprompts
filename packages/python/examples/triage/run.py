"""Offline parse -> assert -> supplied answers -> factors, plus generated import."""

from __future__ import annotations

import json
from pathlib import Path

from systemoneprompts import (
    check_definition,
    create_factor_evaluator,
    create_state_assert,
    generate,
    parse_definition,
)

HERE = Path(__file__).resolve().parent


def main() -> None:
    source = (HERE / "definition.toml").read_text(encoding="utf-8")
    definition = parse_definition(source, filename="definition.toml")
    errors = [item for item in check_definition(definition) if item.severity == "error"]
    if errors:
        raise SystemExit("\n".join(item.message for item in errors))
    state = json.loads((HERE / "state.json").read_text(encoding="utf-8"))
    create_state_assert(definition.requires)(state)
    answers = json.loads((HERE / "answers.json").read_text(encoding="utf-8"))
    factors = create_factor_evaluator(definition.factor_definitions)(answers)
    print(json.dumps(factors, indent=2, sort_keys=True))
    generated = generate(definition, HERE / "definition_generated.py", source_name="definition.toml")
    print(generated)


if __name__ == "__main__":
    main()
