# Examples

Each folder has a definition, its committed `*_generated.py` (kept current by
`uv run systemoneprompts generate examples/*/*.toml`; CI runs `generate --check`),
a `run.py` that calls `TypeSafeClient` directly, and sample state. Set
`TYPESAFE_API_KEY` (a local `.env` is loaded from this package directory) and
run with `uv run python`. `--cache` on the CLI, or `create_caching_fetch()` in
code (see 09), is the cheap edit loop.

| # | Example | Proves |
| --- | --- | --- |
| 01 | `nested-state` | Index paths in `[requires]`, backtick lint |
| 02 | `spam-decomposition` | Atomic Nouls, `at_least` voting, weighted risk in code |
| 03 | `tool-call-verification` | JSON state as evidence; `all` for verified |
| 04 | `contrastive-choice` | Structured Choice criteria; `choice =` predicates |
| 05 | `confidence-routing` | `confidence` gates and gray-band intervals |
| 06 | `frustration-score` | Ordered Score levels; `score = { gte }` |
| 07 | `ticket-triage` | Full canonical workflow (flagship) |
| 08 | `taxonomy-walk` | `walk_taxonomy` |
| 09 | `map-reduce` | `run_many` + `eval --sweep` |
| 10 | `field-extraction` | Structured `field` instructions |
| 11 | `openai-decisions` | Same native questions and results with OpenAI |

```bash
uv run python examples/07-ticket-triage/run.py
uv run systemoneprompts run examples/07-ticket-triage/triage.toml --state examples/07-ticket-triage/states/ticket.json --cache
```

Example 11 uses `OpenAIDecisionsClient` and `OPENAI_API_KEY`; CLI `--cache` uses the same local cache through the Decisions adapter.
