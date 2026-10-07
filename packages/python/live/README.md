# Live tests

Live provider tests are outside the default package check. They require
`TYPESAFE_API_KEY`. The offline parser/evaluator suite must remain
credential-free.

```bash
uv sync --locked --dev
TYPESAFE_API_KEY=... uv run --locked pytest live
```

OpenAI smoke tests require only `OPENAI_API_KEY` and check a live request followed
by identical cached answers with zero usage:

```sh
uv run --locked pytest live/test_openai_decisions.py
```

Run the seven labeled cases and optionally compare the same requests on TypeSafe:

```sh
uv run --locked python live/sample_openai.py --live --compare --report /tmp/decisions.json
```

The sample loads the repository root `.env`, writes answers and usage without
credentials, and performs no retries. Comparison requires `TYPESAFE_API_KEY`;
without it, the report records that probability differences are unavailable.

Run 21 calls per provider with latencies and list-price cost estimates:

```sh
uv run --locked python live/benchmark_providers.py --live --rounds 3 --report /tmp/provider-benchmark.json
```

This requires both keys, disables local caching and retries, and alternates
provider order. See the repository's `docs/provider-benchmark.md` for results.
