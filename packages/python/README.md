# systemoneprompts Python

Define TypeSafe questions, required state, and Boolean factors in TOML.
Generate typed Python modules and call the System One API.

## Quick start

Requires Python 3.11+. Native TypeSafe calls use `TYPESAFE_API_KEY`. OpenRouter
and Cloudflare are described under [Providers](#providers).

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
| `TypeSafeClient` (from `systemoneprompts.client`) | Call System One; accepts `api_key`, `base_url`, `cloudflare_account_id`, `http_client`/`transport`, `timeout`, and `model` |

Invalid TOML throws `SystemOnePromptsError`. Definition errors are returned as
diagnostics; generation rejects definitions with errors.

Generated `<stem>_generated.py` modules export questions, model, metadata,
application data, state assertions, and factor evaluators, with types for
state, answers, and factors. See the [examples](examples/) for patterns.

## Providers

`TypeSafeClient` builds System One JSON `{ state, questions, model }` (this is
what the cache hashes). In Cloudflare mode the body is rewritten before the
network. Cloudflare mode and `base_url` / `TYPESAFE_BASE_URL` cannot be
combined.

### Native TypeSafe

Default. `TYPESAFE_API_KEY` authenticates against `https://api.typesafe.ai`.
Send TypeSafe model ids such as `jev-1.13.0` or `jev-latest`.

```python
client = TypeSafeClient()  # TYPESAFE_API_KEY
```

### OpenRouter

Pass an OpenRouter key as `api_key` and set `base_url` to OpenRouter's System
One API. The client does not read `OPENROUTER_API_KEY`. OpenRouter accepts
`jev-1.13` or `typesafe/jev-1.13`. Extra fields such as `id`, `provider`, and
`usage.cost` are dropped by response validation; TypeScript leaves them on the
object.

```python
import os

from systemoneprompts.client import TypeSafeClient

client = TypeSafeClient(
    api_key=os.environ["TYPESAFE_API_KEY"],  # OpenRouter key
    base_url="https://openrouter.ai/api",
)
response = client.system_one_sync(
    state=state, questions=questions, model="typesafe/jev-1.13"
)
```

CLI: `TYPESAFE_BASE_URL=https://openrouter.ai/api` and put the OpenRouter key
in `TYPESAFE_API_KEY`.

### Cloudflare

Set `cloudflare_account_id` (or `CLOUDFLARE_ACCOUNT_ID`). The client then
treats `api_key` as a Cloudflare token (`CLOUDFLARE_API_TOKEN` when `api_key`
is omitted), posts to
`https://api.cloudflare.com/client/v4/accounts/{id}/ai/run` as
`{ model: "typesafe/jev", input: { state, questions } }`, and unwraps the
Workers AI envelope to `{ model, answers, usage }`. TOML `model` and CLI
`--model` are not sent as the Cloudflare catalog id.

```python
import os

from systemoneprompts.client import TypeSafeClient

client = TypeSafeClient(
    api_key=os.environ["CLOUDFLARE_API_TOKEN"],
    cloudflare_account_id=os.environ["CLOUDFLARE_ACCOUNT_ID"],
)
```

CLI: set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. Do not also set
`TYPESAFE_BASE_URL`. The token needs Account → Workers AI → Read. For
`--cache`, the CLI wraps Cloudflare inside the caching transport so cache keys
stay System One JSON. If you pass your own cache as `transport`, wrap
Cloudflare inside it first; otherwise the client rejects the combination.

| Host | Model to send |
| --- | --- |
| `api.typesafe.ai` | `jev-1.13.0` / `jev-latest` |
| OpenRouter | `jev-1.13` or `typesafe/jev-1.13` |
| Cloudflare | catalog `typesafe/jev` (set by the client) |

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
`--cache` reuses per-question answers from `.systemoneprompts/cache`.

Each eval case has `state` and optional `id`, `labels`, and `factors`.
Labels are Choice strings, Noul Booleans, or integer Score levels.
`--sweep <factor>` compares thresholds.

CLI model precedence: `--model`, TOML `model`, `TYPESAFE_MODEL`,
`TYPESAFE_DEFAULT_MODEL`, then `jev-latest`. In Cloudflare mode `--model` does
not change the catalog id `typesafe/jev`; the reported `response["model"]` is
whatever Cloudflare returned.

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

Live tests require `TYPESAFE_API_KEY`:

```sh
uv sync --locked --dev
sh scripts/run-quiet.sh "Live tests" -- uv run --locked pytest live
```

After release checks pass, `uv run --locked python scripts/publish.py` builds
and publishes the wheel and sdist to PyPI.
