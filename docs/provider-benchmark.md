# Provider benchmark

Measured on 2026-10-07 using the same Noul, Choice, and Score request across
TypeSafe, OpenAI, OpenRouter, and Cloudflare. All 66 network requests succeeded.

| Provider | Reported model | Calls per language | TypeScript median | Python median |
| --- | --- | ---: | ---: | ---: |
| TypeSafe | `jev-1.13.0` | 6 | 297.1 ms | 296.9 ms |
| OpenAI | `gpt-6-luna` | 3 | 422.7 ms | 284.6 ms |
| OpenRouter | `typesafe/jev-1.13-20260917` | 6 | 382.0 ms | 429.2 ms |
| OpenRouter | `openai/gpt-6-luna-decisions-20261006` | 3 | 365.7 ms | 616.2 ms |
| Cloudflare | `clef` | 6 | 564.9 ms | 531.6 ms |
| Cloudflare | `clef-flash` | 6 | 456.6 ms | 532.5 ms |
| Cloudflare (legacy Jev) | `jev-1.13.0` | 3 | 479.1 ms | 415.2 ms |

Each requested model ran three times per language. Results are grouped by
reported model: TypeSafe version pins, OpenRouter Jev aliases, and Cloudflare
short/full catalog IDs resolve to the same models, giving six calls per language
in those rows. Cloudflare covers both Clef and Clef Flash; legacy Jev uses
string-only Score criteria.

Latency measures the first `systemOne` / `system_one` call, including request
encoding, network time, response validation, and writing a fresh local cache.
Retries are disabled; the timeout is 20 seconds. Each probe starts a new client,
then verifies an identical cache hit with zero token usage and no second network
request. The cache hit and process startup are excluded from latency.

The two language workers run concurrently on one workstation. This small,
repeated single-case sample measures integration latency; it does not establish
model accuracy, production throughput, or a reliable provider ranking.

## Run

Use the same live matrix with environment configuration only, repeated three
times. Export all provider credentials or put them in root `.env`.

```sh
for round in 1 2 3; do
  sh packages/typescript/scripts/run-quiet.sh "Provider benchmark" -- \
    python3 tools/run-live-providers.py --live --require-credentials \
    --variation environment --report "/tmp/provider-benchmark-${round}.json"
done
```

If a local Workers AI bearer token is named `CLOUDFLARE_API_KEY`, add
`--cloudflare-token-alias`. Reports include `latencyMs`, reported model, usage,
answers, and network-call counts. See [live provider validation](provider-live-validation.md)
for the complete configuration and CLI matrix.
