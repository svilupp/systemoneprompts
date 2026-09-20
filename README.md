# systemoneprompts

Define TypeSafe questions, required state, and Boolean factors in TOML.
Validate definitions and generate typed modules for TypeScript or Python.

## Install

| Package | Command | Requires |
| --- | --- | --- |
| [TypeScript](packages/typescript/README.md) | `npm install systemoneprompts` or `bun add systemoneprompts` | Node 20+ or Bun |
| [Python](packages/python/README.md) | `pip install systemoneprompts` | Python 3.11+ |

Each package README includes a working example. Both packages ship the same
ten examples.

## Providers

The same `TypeSafeClient` talks to native TypeSafe, OpenRouter, and Cloudflare
Workers AI. Do not combine a custom base URL with Cloudflare mode.

| Host | Auth | How to select | Model to send |
| --- | --- | --- | --- |
| Native TypeSafe (`https://api.typesafe.ai`) | `TYPESAFE_API_KEY` | default | `jev-1.13.0` / `jev-latest` |
| OpenRouter | OpenRouter key as `TYPESAFE_API_KEY` | `TYPESAFE_BASE_URL=https://openrouter.ai/api` | `jev-1.13` or `typesafe/jev-1.13` |
| Cloudflare Workers AI | `CLOUDFLARE_API_TOKEN` | `CLOUDFLARE_ACCOUNT_ID` | catalog `typesafe/jev` (set by the client) |

There is no `OPENROUTER_API_KEY` integration: pass the OpenRouter key as
`apiKey` / `api_key`, or put it in `TYPESAFE_API_KEY` for CLI and default
constructors. OpenRouter is a System One base-URL swap. Cloudflare rewrites
`{ state, questions, model }` to
`POST https://api.cloudflare.com/client/v4/accounts/{id}/ai/run` with
`{ model: "typesafe/jev", input: { state, questions } }` and unwraps the
envelope. TOML `model` and CLI `--model` do not change that catalog id.
`--cache` wraps Cloudflare inside the cache so keys stay System One JSON.
Code samples live in the [TypeScript](packages/typescript/README.md#providers)
and [Python](packages/python/README.md#providers) READMEs.

## Development

Install dependencies from each package directory with
`bun install --frozen-lockfile` or `uv sync --locked --dev`. From the repository root:

```sh
make check
make release-check-typescript
make release-check-python
```

Checks use `scripts/run-quiet.sh`: short output on success, full logs on failure.
Live provider tests are separate.

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
