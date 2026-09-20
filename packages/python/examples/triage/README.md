# Ticket triage example

Parse a definition, assert state, evaluate supplied answers, and consume the
generated module. This example is offline; it does not call TypeSafe.

```bash
uv run systemoneprompts check examples/triage/definition.toml
uv run systemoneprompts generate examples/triage/definition.toml --out examples/triage/
uv run systemoneprompts run examples/triage/definition.toml \
  --state examples/triage/state.json \
  --answers examples/triage/answers.json
uv run python examples/triage/run.py
```
