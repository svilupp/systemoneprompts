# Examples

Each folder contains a definition, committed generated module, and sample state.
Examples 01–10 have direct TypeSafe runners; example 11 uses OpenAI Decisions,
and example 12 uses the CLI with Cloudflare Clef or Clef Flash. The CLI reads
`.env` from the current working directory. Provider examples explain their
credentials and commands. `--cache` is available for all three providers.

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
| 12 | `cloudflare-decisions` | Clef and Clef Flash, provider selection, isolated caches |

```bash
bun run examples/07-ticket-triage/run.ts
bun src/cli/index.ts run examples/07-ticket-triage/triage.toml --state examples/07-ticket-triage/states/ticket.json --cache
```

Example 11 uses `OpenAIDecisionsClient` and `OPENAI_API_KEY`; CLI `--cache` uses the same local cache through the Decisions adapter.

See [example 12](12-cloudflare-decisions/README.md) for repository-root `.env` setup.
