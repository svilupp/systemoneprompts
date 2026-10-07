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

Provider interfaces are not 1:1; supported features and limits vary by provider
and model. Check compatibility before switching providers.

`TypeSafeClient` sends native System One questions to TypeSafe or OpenRouter.
`OpenAIDecisionsClient` translates those questions for direct OpenAI Decisions.
`CloudflareDecisionsClient` handles Clef and Clef Flash. All return the same native
Noul, Choice, and Score answer shapes for factor evaluation.

### Selection and endpoint configuration

| Setting | Precedence / default |
| --- | --- |
| Provider | CLI `--provider` > TOML `provider` > `typesafe` |
| Model | CLI `--model` > TOML `model` > selected provider default |
| Base URL | CLI `--base-url` > TOML `base_url` > selected provider environment > default |
| Key | Constructor key > selected provider environment variable |

Native TypeSafe also reads `TYPESAFE_MODEL`, then `TYPESAFE_DEFAULT_MODEL`, before
its default model. Changing provider preserves an explicit model pin; override
the model too when switching between native and gateway model names.

| Provider | Key | Default model | Base URL / environment override |
| --- | --- | --- | --- |
| `typesafe` | `TYPESAFE_API_KEY` | `jev-latest` | `https://api.typesafe.ai` / `TYPESAFE_BASE_URL` |
| `openai` | `OPENAI_API_KEY` | `gpt-6-luna` | `https://api.openai.com/v1` / `OPENAI_BASE_URL` |
| `openrouter` | `OPENROUTER_API_KEY` | `~typesafe/jev-latest` | `https://openrouter.ai/api/alpha` / `OPENROUTER_BASE_URL` |
| `cloudflare` | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | `clef` | `https://api.cloudflare.com/client/v4/accounts/<account>/ai/run` |

OpenAI and OpenRouter append `/decisions`; Cloudflare appends its catalog model
path; TypeSafe appends `/v1/systemone`. OpenRouter also accepts the full
`/api/alpha/decisions` URL and removes the final suffix before appending it.
Use an HTTP(S) URL without credentials, query, or fragment. An endpoint override
keeps the selected provider's request format. To run Luna through OpenRouter,
select `openrouter` and `openai/gpt-6-luna-decisions`; direct OpenAI uses
`openai` and `gpt-6-luna`.

The CLI reads `.env` only in its current working directory. Programmatic clients
read process environment variables; export credentials before running application
code. Keep API keys outside TOML and generated modules. Generated metadata retains
`provider` and `base_url`; application code must construct the corresponding client.

### Native TypeSafe

Default. `TYPESAFE_API_KEY` authenticates against `https://api.typesafe.ai`.
Send TypeSafe model ids such as `jev-1.13.0` or `jev-latest`.

```python
client = TypeSafeClient()  # TYPESAFE_API_KEY
```

### Legacy Cloudflare Jev

In TypeSafe mode, `CLOUDFLARE_ACCOUNT_ID` selects this route even when
`TYPESAFE_API_KEY` is also set. Unset the account ID to call native TypeSafe.
Explicit OpenAI, OpenRouter, and Clef/Flash providers ignore this legacy switch.

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

Legacy Cloudflare Jev requires string-only Score levels; see the
[live validation record](../../docs/provider-live-validation.md).

### OpenRouter Decisions

Set `OPENROUTER_API_KEY`. Use `~typesafe/jev-latest` for Jev or
`openai/gpt-6-luna-decisions` for Luna. Both use the native question format at
`https://openrouter.ai/api/alpha/decisions`. Do not point the direct
`OpenAIDecisionsClient` codec at this endpoint.

```toml
provider = "openrouter"
model = "~typesafe/jev-latest" # or "openai/gpt-6-luna-decisions"
base_url = "https://openrouter.ai/api/alpha" # optional

[questions.is_urgent]
type = "noul"
instructions = "Does this message convey urgency?"
```

Save this as `decisions.toml` and create `state.json` containing
`{"message":"Help! My payouts have been failing for 3 days."}`:

```sh
systemoneprompts run decisions.toml --state state.json --cache --json
systemoneprompts run decisions.toml --state state.json --model openai/gpt-6-luna-decisions --cache --json
systemoneprompts cache stats --provider openrouter
```

```python
from systemoneprompts.client import TypeSafeClient

client = TypeSafeClient(
    provider="openrouter",
    model="openai/gpt-6-luna-decisions",  # omit for Jev Latest
    # api_key=os.environ["OPENROUTER_API_KEY"],
    # base_url="https://openrouter.ai/api/alpha",
)
try:
    result = client.system_one_sync(
        state={"message": "Help! My payouts have been failing for 3 days."},
        questions={"urgent": {"type": "noul", "instructions": "Is this urgent?"}},
    )
    print(result["answers"]["urgent"]["noul"])
finally:
    client.close()
```

For programmatic native caching, use `create_client(definition, cache=True)` from
`systemoneprompts.provider`, or the native caching transport with
`openrouter_cache_dir()` from `systemoneprompts.dev`. Close the returned raw client.

The older TypeSafe base-URL swap (`TYPESAFE_BASE_URL=https://openrouter.ai/api`
with the OpenRouter key in `TYPESAFE_API_KEY`) still calls `/v1/systemone`.
New integrations should select `openrouter` explicitly.
See the [OpenRouter Decisions reference](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request).

### Direct OpenAI Decisions

Select `provider = "openai"` in TOML or pass `--provider openai` to `run` / `eval`.
CLI selection overrides TOML; omission keeps TypeSafe. Set `OPENAI_API_KEY`.
The default OpenAI model is `gpt-6-luna`; TOML `model` and `--model` override it.
Changing provider preserves a pinned model, so a `jev-latest` definition needs
`--model gpt-6-luna` when run on OpenAI. `check` and `generate` require no key.

```toml
provider = "openai"
[questions.duplicate]
type = "noul"
instructions = "Does the customer report two charges for one order?"
```

```python
from systemoneprompts import OpenAIDecisionsClient

client = OpenAIDecisionsClient()
try:
    result = await client.system_one(
        state="I was charged twice.",
        questions={"duplicate": {"type": "noul", "instructions": "Was the customer charged twice?"}},
    )
    print(result["answers"]["duplicate"]["noul"])
finally:
    client.close()
```

The client accepts the existing Noul, Choice, and Score questions and works with
batch and taxonomy patterns. Choice needs at least two options. Structured
instructions, criteria, and state become canonical JSON text; Python integers
follow JavaScript precision. Score values stay fractional and retain the original
legend. Refusal and malformed output raise `OpenAIDecisionsError`, whose `kind`,
raw `body`, and request ID support inspection. New clients use ten-second attempt
timeouts and two retries. Constructor transport injection is raw network I/O.
OpenAI `--cache` uses the same canonical per-question cache as TypeSafe. The
adapter translates only misses, and malformed or refused live responses write
no new entries. Invalid hits become misses. All-hit usage is zero.

```sh
systemoneprompts run ticket.toml --state ticket.json --provider openai --cache
systemoneprompts cache stats --provider openai
systemoneprompts cache clear --provider openai
```

`--cache-root /path/to/root` selects a custom root for run/eval and cache
management. OpenAI appends `providers/openai-decisions/v1/<base-url-hash>/cache`;
TypeSafe appends `cache`. Defaults remain under `.systemoneprompts`. Cache stats
and clearing default to TypeSafe; pass `--provider openai`, `--provider openrouter`,
or `--provider cloudflare` to select a Decisions scope.
For a custom OpenAI constructor endpoint, use `cache --provider openai --base-url URL`
to manage that scope. Provider, adapter version, and endpoint scopes stay isolated.

See [example 11](examples/11-openai-decisions/README.md) for all three answer types
and labeled cases. Provider probabilities need separate threshold calibration.

```python
from systemoneprompts import OpenAIDecisionsClient
from systemoneprompts.dev import create_cached_openai_decisions_client

network = OpenAIDecisionsClient()
cached = create_cached_openai_decisions_client(client=network, mode="read-write")
try:
    # Use await cached["client"].system_one(state=..., questions=...) as usual.
    print(cached["cache"].dir, cached["cache"].stats())
finally:
    cached["client"].close()  # factory-owned cache workers
    network.close()  # separately owned network client
```

Use the dev factory for caching; passing a bare cache as raw network injection
is rejected because it would bypass canonical request interception.

### Cloudflare Clef and Clef Flash

Set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. The CLI reads `.env` in
the current working directory; programmatic clients read the process environment.
See [example 12](examples/12-cloudflare-decisions/README.md) for repository-root setup. Select `provider = "cloudflare"`
and `model = "clef"` or `"clef-flash"` in TOML, or pass `--provider cloudflare --model clef-flash`.
Full `@cf/cloudflare/` catalog IDs are accepted and canonicalized.

```python
import asyncio
from systemoneprompts import CloudflareDecisionsClient
from systemoneprompts.dev import create_cached_cloudflare_decisions_client

network = CloudflareDecisionsClient(model="clef-flash")
made = create_cached_cloudflare_decisions_client(client=network)
try:
    result = asyncio.run(made["client"].system_one(
        state={"message": "The service is down for all customers."},
        questions={"urgent": {"type": "noul", "instructions": "Is this an outage?"}},
    ))
    print(result["answers"]["urgent"]["noul"])
finally:
    made["client"].close()
    network.close()
```

The clients accept text/JSON state and native Noul, Choice, and Score questions,
including structured instructions and criteria. Clef's image/video extensions are
outside this integration. Calls support 1–64 questions; application IDs are mapped
to transport IDs and restored. Oversized calls fail locally without splitting.

`CloudflareDecisionsError` exposes compatibility, HTTP, transport, timeout, and
response errors, retaining raw response bodies and Cloudflare request IDs. Calls
default to ten-second attempt timeouts and two retries for transient failures.
Malformed successful responses are terminal and write no cache entries.

The cache factory is required for programmatic caching; a bare caching transport
as raw client I/O fails locally. The supplied network resources remain caller-owned.
Default records live under
`.systemoneprompts/providers/cloudflare-decisions/v1/<sha256-run-base-url>/cache/`.
A factory `dir` or CLI `--cache-root` selects the root. Cache management uses
`--provider cloudflare`; `--base-url` selects a custom run-base URL scope.
Model aliases share records, while Clef and Clef Flash have separate model keys.

See [example 12](examples/12-cloudflare-decisions/README.md). Existing
`TypeSafeClient` Cloudflare mode continues to select `typesafe/jev`.

Clef requires at least two Choice alternatives and allows at most ten Score levels.
These provider-specific limits fail locally. Missing or empty instructions use
`Evaluate the supplied evidence against the criteria.`. A Noul question without
instructions must have nonempty outcome criteria; otherwise it fails locally.

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
