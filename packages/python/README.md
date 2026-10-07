# systemoneprompts Python

Define decision questions, required state, and Boolean factors in TOML.
Generate typed Python modules and call TypeSafe, OpenAI, OpenRouter, or Cloudflare.

## Quick start

Requires Python 3.11+. Native TypeSafe calls use `TYPESAFE_API_KEY`. OpenRouter,
Cloudflare, and OpenAI are described under [Providers](#providers).

```sh
pip install systemoneprompts
```

Save as `triage.toml`:

```toml
[requires]
"ticket.message" = "string"

[questions.topic]
type = "choice"
instructions = "Which team should handle `ticket.message`?"

[questions.topic.criteria]
billing = "Charges, invoices, refunds"
orders = "Shipments and deliveries"

[factors]
billing = { ref = "topic", choice = "billing" }
```

```sh
systemoneprompts generate triage.toml
```

```python
from systemoneprompts.client import TypeSafeClient
from triage_generated import assert_state, evaluate_factors, model, questions

state = {"ticket": {"message": "I was charged twice."}}
assert_state(state)
client = TypeSafeClient()
try:
    response = client.system_one_sync(state=state, questions=questions, model=model)
    print(evaluate_factors(response["answers"])["billing"])
finally:
    client.close()
```

Async code can use `await client.system_one(...)`.
`assert_state` validates the original state and returns `None`.

## Definitions and API

Both packages share the [definition format](docs/SPEC.html).
`[requires]` validates state paths, `[questions]` holds TypeSafe question
objects, and `[factors]` computes Boolean results from answers.
Optional top-level `provider`, `model`, and `base_url` configure live CLI calls.
Supported providers are `typesafe`, `openai`, `openrouter`, and `cloudflare`.
Optional `[data]` holds JSON-compatible application data, exported without
sending it to the provider.

Import core functions from `systemoneprompts`:

| Function | Purpose |
| --- | --- |
| `parse_definition(toml)` / `load_definition(path)` | Read a definition |
| `check_definition(definition)` | Collect validation errors and warnings |
| `create_state_assert(definition.requires)` | Validate state |
| `create_factor_evaluator(definition.factor_definitions)` | Compute Boolean factors from answers |
| `generate(definition, output)` | Write a Python module |
| `run_many` / `walk_taxonomy` | Run batches or search Choice trees |
| `TypeSafeClient` (from `systemoneprompts.client`) | Call System One; accepts `provider`, `api_key`, `base_url`, `cloudflare_account_id`, `http_client`/`transport`, `timeout`, and `model` |

Invalid TOML throws `SystemOnePromptsError`. Definition errors are returned as
diagnostics; generation rejects definitions with errors.

Generated `<stem>_generated.py` modules export questions, model, metadata,
application data, state assertions, and factor evaluators, with types for
state, answers, and factors. See the [examples](examples/) for patterns.

## Providers

All clients return native Noul, Choice, and Score answers. Select a provider with
TOML `provider` or CLI `--provider`; omission keeps TypeSafe. Explicit model pins
survive provider changes. CLI `--base-url` overrides TOML `base_url`.

| Provider | Credentials | Default model |
| --- | --- | --- |
| `typesafe` | `TYPESAFE_API_KEY` | `jev-latest` |
| `openai` | `OPENAI_API_KEY` | `gpt-6-luna` |
| `openrouter` | `OPENROUTER_API_KEY` | `~typesafe/jev-latest` |
| `cloudflare` | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | `clef` |

The [specification](docs/SPEC.html#providers-in-020) defines endpoints,
compatibility limits, and cache scopes. Provider features differ; check those
limits before switching. Legacy TypeSafe Cloudflare/Jev mode remains available
and requires string-only Score levels.

```python
from systemoneprompts import OpenAIDecisionsClient

openai = OpenAIDecisionsClient()
try:
    result = await openai.system_one(
        state="I was charged twice.",
        questions={"duplicate": {"type": "noul", "instructions": "Was the customer charged twice?"}},
    )
    print(result["answers"]["duplicate"]["noul"])
finally:
    openai.close()
```

Use `TypeSafeClient()` for native TypeSafe,
`TypeSafeClient(provider="openrouter")` for OpenRouter, or
`CloudflareDecisionsClient(model="clef-flash")` for Clef Flash.
For OpenRouter Luna, set `model="openai/gpt-6-luna-decisions"`.
Constructor `api_key` and `base_url` override environment configuration.

### Programmatic caching

For TypeSafe and OpenRouter, use `create_client(definition, cache=True)` from
`systemoneprompts.provider`; close its returned raw client. Direct OpenAI and
Cloudflare use dev factories:

```python
from systemoneprompts.dev import create_cached_openai_decisions_client

network = OpenAIDecisionsClient()
cached = create_cached_openai_decisions_client(client=network)
try:
    result = await cached["client"].system_one(
        state="I was charged twice.",
        questions={"duplicate": {"type": "noul", "instructions": "Was the customer charged twice?"}},
    )
    print(result["answers"]["duplicate"]["noul"])
finally:
    cached["client"].close()
    network.close()
```

Use `create_cached_cloudflare_decisions_client` for Clef. Pass `dir` for a custom
cache root and `mode` for `read-only` or `refresh`. Close factory-owned workers
separately from the network client. Bare caching transport injection is rejected.

See [example 11](examples/11-openai-decisions/README.md) and
[example 12](examples/12-cloudflare-decisions/README.md) for complete definitions
with all three question types and eval cases.

## CLI

```sh
systemoneprompts check triage.toml --strict
systemoneprompts generate triage.toml --check
systemoneprompts run triage.toml --state state.json --answers answers.json
systemoneprompts run triage.toml --state state.json --cache --json
systemoneprompts eval triage.toml --cases cases.jsonl --report report.json
systemoneprompts cache stats
```

`generate --check` fails if generated files are stale.
`run --answers` evaluates saved answers without an API call.
State can come from stdin with `--state -` or by omitting `--state`.
`--cache` reuses per-question answers from the selected provider scope below.

Each eval case has `state` and optional `id`, `labels`, and `factors`.
Labels are Choice strings, Noul Booleans, or integer Score levels.
`--sweep <factor>` compares thresholds.

For TypeSafe, CLI model precedence is `--model`, TOML `model`, `TYPESAFE_MODEL`,
`TYPESAFE_DEFAULT_MODEL`, then `jev-latest`. In Cloudflare mode `--model` does
not change the catalog id `typesafe/jev`; the reported `response["model"]` is
whatever Cloudflare returned.

### Cache directories

`--cache-root` replaces `.systemoneprompts`; scopes below are appended to that root.
All-hit requests return the original answers and zero token usage.

| Provider | Directory under cache root |
| --- | --- |
| TypeSafe / legacy Cloudflare Jev | `cache/` |
| Direct OpenAI | `providers/openai-decisions/v1/<base-url-hash>/cache/` |
| OpenRouter | `providers/openrouter-decisions/v1/<base-url-hash>/cache/` |
| Clef / Clef Flash | `providers/cloudflare-decisions/v1/<run-base-url-hash>/cache/` |

Models have separate record keys. Decisions endpoints have separate scopes;
credentials do not enter hashes. `cache stats` and `cache clear` do not read TOML.
For a TOML or constructor custom endpoint, repeat `--base-url` when managing its
cache, or set the matching provider environment URL. `--base-url` on cache
management is supported for Decisions providers only.

```sh
systemoneprompts cache stats --provider openrouter --cache-root /tmp/decisions-cache --base-url https://openrouter.ai/api/alpha
systemoneprompts cache clear --provider openrouter --cache-root /tmp/decisions-cache --base-url https://openrouter.ai/api/alpha
```

## Development

Run from this package directory:

```sh
uv sync --locked --dev
sh scripts/run-quiet.sh "Checks" -- uv run --locked python scripts/check.py
sh scripts/run-quiet.sh "Release checks" -- uv run --locked python scripts/release-check.py
```

Checks cover lint, tests, types, builds, shared test cases, and generated
examples. Release checks also test wheel and sdist installs and a copy of the
package outside the repository. Use `scripts/run-quiet.sh` for focused tests
too; it retains full logs and prints failures.

After editing example definitions, run
`uv run --locked systemoneprompts generate examples/*/*.toml`.

Live tests are explicit; each provider needs its own credentials. Missing keys
skip that provider in the package smoke suite:

```sh
uv sync --locked --dev
sh scripts/run-quiet.sh "Live tests" -- uv run --locked pytest live
```

After release checks pass, `uv run --locked python scripts/publish.py` builds
and publishes the wheel and sdist to PyPI.

For the full provider/model/configuration matrix in this checkout, run from the
repository root:

```sh
python3 tools/run-live-providers.py --live --language python --report /tmp/python-providers.json
```

The matrix checks all three answer types, environment and explicit constructor
configuration, live CLI run/eval, cached repeats, and cache stats/clear. It writes
passes, failures, and credential skips to JSON. See [live checks](live/README.md) for the model list and setup.
