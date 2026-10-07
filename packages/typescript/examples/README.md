# Examples

Each folder has a definition, its committed `*.generated.ts` (kept current by `bun run examples:generate`; CI runs `generate --check`), a `run.ts` that calls `TypeSafeClient` directly, and sample state. Set `TYPESAFE_API_KEY` (a local `.env` is loaded by Bun) and run with Bun; no build step is needed. `--cache` on the CLI, or `createCachingFetch()` in code (see 09), is the cheap edit loop.

| # | Example | Proves |
| --- | --- | --- |
| 01 | `nested-state` | Index paths in `[requires]`, backtick lint |
| 02 | `spam-decomposition` | Atomic Nouls, `at_least` voting, weighted risk in code |
| 03 | `tool-call-verification` | JSON state as evidence; `all` for verified |
| 04 | `contrastive-choice` | Structured Choice criteria; `choice =` predicates |
| 05 | `confidence-routing` | `confidence` gates and gray-band intervals |
| 06 | `frustration-score` | Ordered Score levels; `score = { gte }` |
| 07 | `ticket-triage` | Full canonical workflow (flagship) |
| 08 | `taxonomy-walk` | `walkTaxonomy` |
| 09 | `map-reduce` | `runMany` + `eval --sweep` |
| 10 | `field-extraction` | Structured `field` instructions |
| 11 | `openai-decisions` | Same native questions and results with OpenAI |

```bash
bun run examples/07-ticket-triage/run.ts
bun src/cli/index.ts run examples/07-ticket-triage/triage.toml --state examples/07-ticket-triage/states/ticket.json --cache
```

Example 11 uses `OpenAIDecisionsClient` and `OPENAI_API_KEY`; CLI `--cache` uses the same local cache through the Decisions adapter.
