# Live provider testing

Live checks make paid requests and stay outside deterministic checks. Export the
credentials listed in the [specification](SPEC.md#providers-in-020).

From the repository root:

```sh
sh packages/typescript/scripts/run-quiet.sh "Live providers" -- python3 tools/run-live-providers.py --live --require-credentials --report /tmp/provider-matrix.json
```

The runner loads root `.env`, preserves exported values, and writes redacted
results to the requested path. `--require-credentials` makes missing credentials
fail the run; omit it only for a partial local run. Keep execution reports outside
the source tree. Add `--language typescript|python` or `--provider NAME` to narrow
the run. Repeat `--variation environment|explicit|text|cli|stdin` to select checks.

Both TypeScript and Python run every row below, with five variations per model
(environment, explicit configuration, text state, CLI file state, CLI stdin):

| Provider | Models | Credentials |
| --- | --- | --- |
| TypeSafe | `jev-latest`, `jev-1.13.0` | `TYPESAFE_API_KEY` |
| OpenAI | `gpt-6-luna` | `OPENAI_API_KEY` |
| OpenRouter | `~typesafe/jev-latest`, `typesafe/jev-1.13`, `openai/gpt-6-luna-decisions` | `OPENROUTER_API_KEY` |
| Cloudflare | `clef`, `clef-flash`, `@cf/cloudflare/clef`, `@cf/cloudflare/clef-flash` | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` |
| Legacy Cloudflare | `typesafe/jev` (fixed catalog ID) | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` |

Verified on 2026-10-07: all 110 checks passed, with no failures or skips.

If a local Workers AI bearer token is named `CLOUDFLARE_API_KEY`, add `--cloudflare-token-alias`; global API keys are unsupported.

All use one small native sample with Noul, Choice, and Score questions.
Programmatic matrix checks verify native answers, one network request followed
by an identical cache hit, and zero all-hit usage. CLI checks cover file/stdin state,
eval, scoped cache stats, and clear.

## Package smoke checks

From the selected package directory, after exporting credentials:

```sh
# TypeScript
sh scripts/run-quiet.sh "Live smoke" -- bun run test:live
# Python
sh scripts/run-quiet.sh "Live smoke" -- uv run --locked pytest live
```

Package smoke checks cover native TypeSafe, direct OpenAI, and both Clef models.
The full matrix adds OpenRouter, endpoint overrides, catalog aliases, legacy
routing, and CLI management. These checks verify integration behavior, not model accuracy.

## Legacy Cloudflare Jev limitation

Legacy `typesafe/jev` rejects structured Score levels with an upstream HTTP 500.
Use string-only Score criteria. Text and JSON state both work with those levels.
The default matrix uses `text-simple` for legacy Jev; other providers use text
with structured criteria. Use `--variation json-structured` explicitly to
exercise the upstream limitation; that diagnostic is expected to fail.

```sh
sh packages/typescript/scripts/run-quiet.sh "Legacy diagnostics" -- python3 tools/run-live-providers.py --live --provider cloudflare-jev --variation text-simple --variation json-structured --report /tmp/legacy-diagnostics.json
```
