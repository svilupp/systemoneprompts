# systemoneprompts

Define decision questions, required state, and Boolean factors in TOML.
Validate definitions and generate typed modules for TypeScript or Python.

## Install

| Package | Command | Requires |
| --- | --- | --- |
| [TypeScript](packages/typescript/README.md) | `npm install systemoneprompts` or `bun add systemoneprompts` | Node 20+ or Bun |
| [Python](packages/python/README.md) | `pip install systemoneprompts` | Python 3.11+ |

Each package README includes a working example. Both packages ship the same
twelve examples.

## Providers

Provider interfaces are not 1:1; supported features and limits vary by provider
and model. Check compatibility before switching providers.

The same `TypeSafeClient` talks to native TypeSafe, OpenRouter, and Cloudflare
Workers AI. `OpenAIDecisionsClient` calls OpenAI Decisions with the same native
questions and normalized answers. `CloudflareDecisionsClient` selects Clef or
Clef Flash. Do not combine a custom TypeSafe base URL with legacy Cloudflare mode.

| Host | Auth | How to select | Model to send |
| --- | --- | --- | --- |
| Native TypeSafe (`https://api.typesafe.ai`) | `TYPESAFE_API_KEY` | default | `jev-1.13.0` / `jev-latest` |
| OpenRouter Decisions | `OPENROUTER_API_KEY` | TOML `provider = "openrouter"` or CLI `--provider openrouter` | `~typesafe/jev-latest` / `openai/gpt-6-luna-decisions` |
| OpenAI Decisions (`https://api.openai.com/v1/decisions`) | `OPENAI_API_KEY` | TOML `provider = "openai"` or CLI `--provider openai` | `gpt-6-luna` |
| Cloudflare Clef / Clef Flash | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | TOML `provider = "cloudflare"` or CLI `--provider cloudflare` | `clef` / `clef-flash` |
| Cloudflare Workers AI (Jev) | `CLOUDFLARE_API_TOKEN` | `CLOUDFLARE_ACCOUNT_ID` | catalog `typesafe/jev` (set by the client) |

OpenRouter Decisions uses `https://openrouter.ai/api/alpha/decisions`. Set
`OPENROUTER_API_KEY` and select `provider = "openrouter"`; use `OPENROUTER_BASE_URL`,
TOML `base_url`, or CLI `--base-url` to override its base. The older TypeSafe
base-URL swap remains available. In TypeSafe mode, `CLOUDFLARE_ACCOUNT_ID`
selects legacy Cloudflare Jev; unset it for native TypeSafe. Legacy
`TypeSafeClient` Cloudflare/Jev mode rewrites
`{ state, questions, model }` to
`POST https://api.cloudflare.com/client/v4/accounts/{id}/ai/run` with
`{ model: "typesafe/jev", input: { state, questions } }` and unwraps the
envelope. TOML `model` and CLI `--model` do not change that catalog id.
`--cache` wraps Cloudflare inside the cache so keys stay System One JSON.
Code samples live in the [TypeScript](packages/typescript/README.md#providers)
and [Python](packages/python/README.md#providers) READMEs.

`OpenAIDecisionsClient` adds OpenAI's Decisions backend with the same questions
and normalized answers. Set `OPENAI_API_KEY`, then select `provider = "openai"`
in TOML or `--provider openai` on `run` / `eval`. It defaults to `gpt-6-luna`;
explicit model pins are preserved. `--cache` reuses the local per-question cache,
with a provider/version/endpoint scope for OpenAI.

`CloudflareDecisionsClient` selects Clef or Clef Flash explicitly. It supports the
same JEV questions and JSON/text state, including structured instructions and criteria.
Full catalog model IDs are aliases. Calls are limited to 64 questions; arbitrary
application IDs are mapped and restored. Image/video extensions are outside this
integration. `--cache` isolates Cloudflare Decisions from other providers and keeps
Clef and Clef Flash separate. See [example 12](packages/typescript/examples/12-cloudflare-decisions/README.md).

## OpenRouter Decisions

Set `OPENROUTER_API_KEY`, then choose either model in your definition:

```toml
provider = "openrouter"
model = "~typesafe/jev-latest" # or "openai/gpt-6-luna-decisions"
base_url = "https://openrouter.ai/api/alpha" # optional

[questions.is_urgent]
type = "noul"
instructions = "Does this message convey urgency?"
```

```sh
systemoneprompts run decisions.toml --state state.json --cache
systemoneprompts run decisions.toml --state state.json --model openai/gpt-6-luna-decisions
systemoneprompts cache stats --provider openrouter
```

Constructor equivalents: TypeScript `new TypeSafeClient({provider: "openrouter"})`;
Python `TypeSafeClient(provider="openrouter")` from `systemoneprompts.client`.
Pass `apiKey` / `api_key` and `baseURL` / `base_url` to override environment settings.
`OPENROUTER_BASE_URL` sets the default base; `--base-url` overrides TOML and environment.
OpenRouter models use the native question format, including Luna. The direct
`OpenAIDecisionsClient` retains its OpenAI format and accepts `OPENAI_BASE_URL`.
See the [OpenRouter Decisions reference](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request).

## 0.2.0 release record

Adds OpenAI Decisions in both languages, provider selection, and local caching.
Current `provider` values are `typesafe`, `openai`, `openrouter`, and `cloudflare`.
Existing definitions that omit it keep their behavior. OpenAI supports text/JSON
state and Noul, Choice, and Score questions; multimodal input is outside this API.
Other explicit model IDs pass through to the selected provider, which validates
availability. The OpenAI integration is verified with `gpt-6-luna`.

See the [changelog](CHANGELOG.md) for release notes.

## Development

Install dependencies from each package directory with
`bun install --frozen-lockfile` or `uv sync --locked --dev`. From the repository root:

```sh
make check
make release-check-typescript
make release-check-python
```

Checks use `scripts/run-quiet.sh`: short output on success, full logs on failure.
The [live validation record](docs/provider-live-validation.md) covers both languages.
Live provider tests are separate. Run all documented provider/model variations
in both languages with:

```sh
python3 tools/run-live-providers.py --live --report /tmp/provider-matrix.json
```

The runner loads repository-root `.env` and exported variables, preserves exported
values, and reports missing credentials as skips. See the package live guides for
coverage and the local Cloudflare token alias.

Both packages follow the [v1 specification](docs/SPEC.md) and
[shared test cases](conformance/v1/). After editing shared files, run
`make sync-shared`.

## Publish

```sh
make publish-typescript
make publish-python
```

Each command runs release checks, builds, and uploads its package.
See [releasing](docs/releasing.md) for setup.
