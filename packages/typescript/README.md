# systemoneprompts

Define decision questions, required state, and Boolean factors in TOML.
Generate typed TypeScript modules and call TypeSafe, OpenAI, OpenRouter, or Cloudflare.

## Quick start

Requires Node 20+ or Bun. Set `TYPESAFE_API_KEY` for native TypeSafe API calls.
OpenAI, OpenRouter, and Cloudflare credentials are described under [Providers](#providers).

```sh
npm install systemoneprompts
# or: bun add systemoneprompts
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
npx systemoneprompts generate triage.toml
# or: bunx systemoneprompts generate triage.toml
```

Use the generated module in your TypeScript app:

```ts
import { TypeSafeClient } from "systemoneprompts";
import { questions, model, assertState, evaluateFactors } from "./triage.generated.js";

const state = { ticket: { message: "I was charged twice." } };
assertState(state);
const response = await new TypeSafeClient().systemOne({ state, questions, model });
console.log(evaluateFactors(response.answers).billing);
```

`assertState` validates and narrows the original state. Generated types cover
state, answers, and factors.

## Definitions

| Field | Purpose |
| --- | --- |
| `title`, `version`, `description` | Optional metadata |
| `model` | Optional model for API calls |
| `provider` | Optional `typesafe`, `openai`, `openrouter`, or `cloudflare` |
| `base_url` | Optional HTTP(S) endpoint base; CLI override takes precedence |
| `[requires]` | Required state paths and types |
| `[questions]` | TypeSafe `noul`, `choice`, or `score` questions |
| `[factors]` | Boolean results computed from answers |
| `[data]` | Optional application data, exported as `data` |

Requirements accept `string`, `number`, `boolean`, `array`, `object`, `null`,
and `exists`. Paths support dots, indexes, and wildcards:
`ticket.message`, `tickets[0].message`, `tickets[].message`.
An empty array satisfies a wildcard requirement.

Questions use TypeSafe's `type`, `instructions`, and `criteria` fields.
Instructions and criteria entries can be strings, tables, or arrays.
At least one question is required.

Factors use `all`, `any`, `not`, `at_least`, or a `ref` predicate.
Bare Noul references use a threshold of `0.5`; Choice and Score answers need
a predicate. Missing answers raise errors, except in a `known`-only predicate.

`[data]` holds JSON-compatible application data. Your code defines its schema
and use; the package preserves it without sending it to the provider.

See the [specification](docs/SPEC.html) for the full rules,
[examples](examples/) for patterns, and the
[agent guide](docs/skills/systemoneprompts/SKILL.md) for authoring definitions.

## API

Import core functions from `systemoneprompts`:

| Function | Purpose |
| --- | --- |
| `parseDefinition(toml)` / `loadDefinition(path)` | Read a definition |
| `checkDefinition(def)` | Collect validation errors and warnings |
| `createStateAssert(def.requires)` | Validate state |
| `createFactorEvaluator(def.factorDefinitions)` | Compute Boolean factors from answers |
| `generate(toml, { filename })` | Generate TypeScript source |
| `TypeSafeClient` | Call System One; accepts `provider`, `apiKey`, `baseURL`, `cloudflareAccountId`, `fetch`, and `timeout` |

Invalid TOML throws `SystemOnePromptsError`. Definition errors are returned as
diagnostics; generation rejects definitions with errors.

`systemoneprompts/dev` exports `createCachingFetch` for per-question caching.
`systemoneprompts/patterns` exports `runMany` for batches and `walkTaxonomy`
for Choice tree searches.

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

```ts
import { OpenAIDecisionsClient } from "systemoneprompts";

const openai = new OpenAIDecisionsClient();

const result = await openai.systemOne({
  state: "I was charged twice.",
  questions: { duplicate: { type: "noul", instructions: "Was the customer charged twice?" } },
});
console.log(result.answers.duplicate.noul);
```

Use `new TypeSafeClient()` for native TypeSafe,
`new TypeSafeClient({ provider: "openrouter" })` for OpenRouter, or
`new CloudflareDecisionsClient({ defaultModel: "clef-flash" })` for Clef Flash.
For OpenRouter Luna, set `defaultModel: "openai/gpt-6-luna-decisions"`.
Constructor `apiKey` and `baseURL` override environment configuration.

### Programmatic caching

Native TypeSafe and OpenRouter use `createCachingFetch`. Use `openRouterCacheDir()`
for the gateway scope. Direct OpenAI and Cloudflare use their dev factories so
wire translation happens inside the per-question cache:

```ts
import { createCachedOpenAIDecisionsClient } from "systemoneprompts/dev";

const { client, cache } = createCachedOpenAIDecisionsClient({ client: openai });
const result = await client.systemOne({
  state: "I was charged twice.",
  questions: { duplicate: { type: "noul", instructions: "Was the customer charged twice?" } },
});
console.log(result.answers.duplicate.noul, cache.stats());
```

Use `createCachedCloudflareDecisionsClient` for Clef. Pass `dir` for a custom
cache root and `mode` for `read-only` or `refresh`. Bare caching fetch injection
into the OpenAI or Clef client is rejected.

See [example 11](examples/11-openai-decisions/README.md) and
[example 12](examples/12-cloudflare-decisions/README.md) for complete definitions
with all three question types and eval cases.

## CLI

```sh
npx systemoneprompts check triage.toml --strict
npx systemoneprompts generate triage.toml --check
npx systemoneprompts run triage.toml --state state.json --cache --json
npx systemoneprompts eval triage.toml --cases cases.jsonl --report report.json
npx systemoneprompts cache stats
# bunx systemoneprompts works the same way
```

`generate --check` fails if generated files are stale. `run` accepts state from
stdin when `--state` is omitted. `--cache` reuses per-question answers from the selected provider scope below.

Each eval case has `state` and optional `id`, `labels`, and `factors`.
Labels are Choice strings, Noul Booleans, or integer Score levels.
`--sweep <factor>` compares thresholds.

For TypeSafe, CLI model precedence is `--model`, TOML `model`, `TYPESAFE_MODEL`,
`TYPESAFE_DEFAULT_MODEL`, then `jev-latest`. In Cloudflare mode `--model` does
not change the catalog id `typesafe/jev`; the reported `response.model` is
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
bun install --frozen-lockfile
sh scripts/run-quiet.sh "Checks" -- bun run check
sh scripts/run-quiet.sh "Release checks" -- bun run release:check
```

Checks cover types, lint, tests, examples, and public exports. Release checks
also pack the npm archive and smoke it from npm and bun consumers under Node
and Bun. Use `scripts/run-quiet.sh` for focused tests too; it retains full
logs and prints failures.

After editing example definitions, run `bun run examples:generate`.
Live tests are explicit; each provider needs its own credentials. Missing keys
skip that provider in the package smoke suite:

```sh
sh scripts/run-quiet.sh "Live tests" -- bun run test:live
```

After release checks pass, `bun run release:publish` builds and publishes to npm.

For the full provider/model/configuration matrix in this checkout, run from the
repository root:

```sh
python3 tools/run-live-providers.py --live --language typescript --report /tmp/typescript-providers.json
```

The matrix checks all three answer types, environment and explicit constructor
configuration, live CLI run/eval, cached repeats, and cache stats/clear. It writes
passes, failures, and credential skips to JSON. See [live checks](live/README.md) for the model list and setup.
