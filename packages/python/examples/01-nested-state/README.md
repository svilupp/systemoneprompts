# 01 — Nested state

Proves index paths in `[requires]` (`support.tickets[0].message`) and backtick lint against those paths.

```bash
uv run python examples/01-nested-state/run.py
# or
uv run systemoneprompts run examples/01-nested-state/nested-state.toml --state examples/01-nested-state/states/ticket.json --cache
```
