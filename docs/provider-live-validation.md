# Live provider testing

Live checks make paid requests and stay outside deterministic checks. Export the
credentials listed in the [specification](SPEC.md#providers-in-020).

From the repository root:

```sh
sh packages/typescript/scripts/run-quiet.sh "Live providers" -- python3 tools/run-live-providers.py --live --report /tmp/provider-matrix.json
```

The runner loads root `.env`, preserves exported values, skips missing credentials,
and writes redacted results to the requested path. Keep execution reports outside
the source tree. Add `--language typescript|python` or `--provider NAME` to narrow
the run. Repeat `--variation environment|explicit|text|cli|stdin` to select checks.

The matrix covers native TypeSafe, OpenAI, OpenRouter Jev/Luna, Clef/Clef Flash
and their catalog aliases, and legacy Cloudflare Jev. All use one small native
sample with Noul, Choice, and Score questions. Programmatic matrix checks
verify native answers, one network request followed by
an identical cache hit, and zero all-hit usage. CLI checks cover file/stdin state,
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
The full matrix adds OpenRouter, endpoint overrides, catalog aliases, legacy routing, and CLI
management. These checks verify integration behavior, not model accuracy.

## Legacy Cloudflare Jev limitation

Legacy `typesafe/jev` rejects structured Score levels with an upstream HTTP 500.
Use string-only Score criteria. Text and JSON state both work with those levels.
The matrix retains a structured-Score diagnostic variation and reports its failure.
Use `--variation text-simple` to check the supported form.

```sh
sh packages/typescript/scripts/run-quiet.sh "Legacy diagnostics" -- python3 tools/run-live-providers.py --live --provider cloudflare-jev --variation text-simple --variation json-structured --report /tmp/legacy-diagnostics.json
```
