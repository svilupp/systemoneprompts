# 07 — Ticket triage (flagship)

The full canonical workflow: seven TypeSafe questions, Boolean factors, and weighted spam risk in ordinary Python.

```bash
uv run python examples/07-ticket-triage/run.py
uv run systemoneprompts run examples/07-ticket-triage/triage.toml --state examples/07-ticket-triage/states/ticket.json --cache
```

A second `--cache` run should spend 0 tokens.
