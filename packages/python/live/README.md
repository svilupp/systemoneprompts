# Live provider checks

Live checks make paid provider requests and stay outside deterministic package checks.
Set the credentials for each provider you want to exercise:

| Provider | Credentials | Models checked |
| --- | --- | --- |
| Native TypeSafe | `TYPESAFE_API_KEY` | `jev-latest`, `jev-1.13.0` |
| Direct OpenAI | `OPENAI_API_KEY` | `gpt-6-luna` |
| OpenRouter | `OPENROUTER_API_KEY` | `~typesafe/jev-latest`, `typesafe/jev-1.13`, `openai/gpt-6-luna-decisions` |
| Cloudflare Decisions | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | Clef / Clef Flash, short and full catalog aliases |
| Legacy Cloudflare Jev | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | catalog `typesafe/jev` |

## Full matrix

Run from the repository root:

```sh
sh packages/typescript/scripts/run-quiet.sh "Live providers" -- python3 tools/run-live-providers.py --live --report /tmp/provider-matrix.json
```

Add `--language typescript` or `--language python` to run one package. The runner
loads repository-root `.env`, preserves exported variables, and runs from temporary
directories so package CLI dotenv files cannot change provider selection.
Missing credentials become explicit skips; failures remain failures. It writes
redacted JSON results with model, usage, timing, and error details.

Five variations run for every provider/model in each language:

1. Environment credentials and base URL, JSON state.
2. Explicit constructor credentials and URL, including full Decisions URL suffixes.
3. Text state with structured Score criteria.
4. CLI `run --state`, repeated cached run, `eval`, `cache stats`, and `cache clear`.
5. CLI state through stdin, followed by the same cache and eval checks.

Every variation uses Noul, Choice, and Score. Programmatic probes disable retries,
set a 20-second attempt timeout, validate native answers, and assert one network
call for a request followed by a cache hit. CLI probes use normal client defaults.
All-hit requests must preserve answers and report zero token usage. Temporary
cache directories are removed after each variation. This checks transport and
configuration; it does not measure model accuracy.

The [2026-10-07 validation record](../../../docs/provider-live-validation.md)
passed 108/110 main checks. Legacy Cloudflare Jev rejected structured Score
criteria with HTTP 500 in both languages; its string-only Score checks passed.
The runner reports this as failure rather than hiding it.

Use repeatable `--variation environment|explicit|text|cli|stdin` options to rerun
only selected cases. The complete matrix contains 110 checks and normally makes
110 small network requests when every credential is available.

This checkout stores a Workers AI bearer token under the local name
`CLOUDFLARE_API_KEY`. The clients require `CLOUDFLARE_API_TOKEN`. Add
`--cloudflare-token-alias` to the runner only when that local value is a bearer
token; global Cloudflare API keys are not supported. The runner maps the alias
in child environments and leaves `.env` unchanged.

## Package smoke suite

Run from the package directory after exporting credentials. Package smoke tests
load only the current directory's `.env`; the matrix handles root `.env` loading.

```sh
sh scripts/run-quiet.sh "Live smoke" -- uv run --locked pytest live
```

The smoke suite covers native Jev, direct OpenAI, and both Clef models. Use the
full matrix for OpenRouter, explicit URLs, stdin, aliases, and CLI cache management.

## Labeled OpenAI sample and benchmark

```sh
sh scripts/run-quiet.sh "OpenAI sample" -- uv run --locked python live/sample_openai.py --live --compare --report /tmp/decisions.json
sh scripts/run-quiet.sh "Provider benchmark" -- uv run --locked python live/benchmark_providers.py --live --rounds 3 --report /tmp/provider-benchmark.json
```

The sample runs seven labeled cases and optionally compares TypeSafe when its
key is available. The benchmark runs 21 uncached calls per provider with retries
disabled. Both load repository-root `.env`; the benchmark requires native TypeSafe
and OpenAI keys. Results include answers, usage, and timings without credentials.
