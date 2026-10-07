# Live provider validation

Executed on 2026-10-07 against the TypeScript and Python source packages.
Credentials came from exported variables and repository-root `.env`; the local
Cloudflare bearer-token alias was mapped only in child environments.

The main matrix passed **108 of 110 checks**, with no credential skips. The two
failures were the same legacy Cloudflare Jev structured Score limitation in both
languages. Four targeted diagnostic checks then passed text state with string-only
Score criteria and reproduced the structured Score failure with JSON state.
Total evidence: **110 passes, 4 failures, 0 skips across 114 checks**.

| Provider / model | TypeScript | Python |
| --- | --- | --- |
| TypeSafe `jev-latest` | 5/5 | 5/5 |
| TypeSafe `jev-1.13.0` | 5/5 | 5/5 |
| Direct OpenAI `gpt-6-luna` | 5/5 | 5/5 |
| OpenRouter `~typesafe/jev-latest` | 5/5 | 5/5 |
| OpenRouter `typesafe/jev-1.13` | 5/5 | 5/5 |
| OpenRouter `openai/gpt-6-luna-decisions` | 5/5 | 5/5 |
| Cloudflare `clef` | 5/5 | 5/5 |
| Cloudflare `clef-flash` | 5/5 | 5/5 |
| Cloudflare `@cf/cloudflare/clef` | 5/5 | 5/5 |
| Cloudflare `@cf/cloudflare/clef-flash` | 5/5 | 5/5 |
| Legacy Cloudflare Jev `typesafe/jev` | 4/5 | 4/5 |

The five variations cover environment configuration, explicit constructor keys
and URLs, text state with structured Score criteria, CLI file state, and CLI stdin.
Every variation asks Noul, Choice, and Score questions. Programmatic probes assert
exactly one network call for a request followed by an identical cache hit. CLI
variations run twice, execute eval, inspect cache stats, and clear the selected scope.
All-hit usage must be zero. No accuracy threshold is inferred from these smoke tests.

## Legacy Cloudflare Jev limitation

The gateway returned HTTP 500 with `Model execution failed (Failed to parse model
output)` when a Score rubric contained an object entry. This happened with both
JSON state and text state in both packages. String-only Score levels passed with
both state forms. Structured Choice instructions and Noul outcome criteria passed.
The adapters preserve payloads and surface the upstream failure; there is no
silent conversion or fallback. Use string-only Score levels on this legacy route,
or use one of the other validated providers.

## Reproduce

```sh
sh packages/typescript/scripts/run-quiet.sh "Live matrix" -- python3 tools/run-live-providers.py --live --cloudflare-token-alias --report /tmp/provider-matrix.json
sh packages/typescript/scripts/run-quiet.sh "Legacy diagnostics" -- python3 tools/run-live-providers.py --live --cloudflare-token-alias --provider cloudflare-jev --variation text-simple --variation json-structured --report /tmp/legacy-diagnostics.json
```

Omit `--cloudflare-token-alias` when `CLOUDFLARE_API_TOKEN` is already exported.
The runner deliberately returns nonzero for failed variations, including this
known upstream limitation. See the [redacted JSON execution record](provider-live-results.json)
for each variation's answers, reported model, token usage, timing, and error.
