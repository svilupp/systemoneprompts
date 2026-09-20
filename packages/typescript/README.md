# systemoneprompts

Define TypeSafe questions, required state, and Boolean factors in TOML.
Generate typed TypeScript modules and call the System One API.

## Quick start

Requires Node 20+ or Bun. Set `TYPESAFE_API_KEY` for native TypeSafe API calls.
OpenRouter and Cloudflare credentials are described under [Providers](#providers).

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
| `TypeSafeClient` | Call System One; accepts `apiKey`, `baseURL`, `cloudflareAccountId`, `fetch`, and `timeout` |

Invalid TOML throws `SystemOnePromptsError`. Definition errors are returned as
diagnostics; generation rejects definitions with errors.

`systemoneprompts/dev` exports `createCachingFetch` for per-question caching.
`systemoneprompts/patterns` exports `runMany` for batches and `walkTaxonomy`
for Choice tree searches.

## Providers

The client builds System One JSON `{ state, questions, model }` (this is what
the cache hashes). Where that JSON goes depends on how you construct
`TypeSafeClient`. In Cloudflare mode the body is rewritten before the network.
Cloudflare mode and `baseURL` / `TYPESAFE_BASE_URL` cannot be combined.

### Native TypeSafe

Default. `TYPESAFE_API_KEY` authenticates against `https://api.typesafe.ai`.
Send TypeSafe model ids such as `jev-1.13.0` or `jev-latest`.

```ts
const client = new TypeSafeClient(); // TYPESAFE_API_KEY
```

### OpenRouter

Point `baseURL` at OpenRouter's System One API and pass an OpenRouter key as
`apiKey`. The client does not read `OPENROUTER_API_KEY`. OpenRouter accepts
`jev-1.13` or `typesafe/jev-1.13`. Extra response fields such as `id`,
`provider`, and `usage.cost` are left in place; Python validation strips them.

```ts
const client = new TypeSafeClient({
  apiKey: process.env.TYPESAFE_API_KEY, // OpenRouter key
  baseURL: "https://openrouter.ai/api",
});
await client.systemOne({ state, questions, model: "typesafe/jev-1.13" });
```

CLI: `TYPESAFE_BASE_URL=https://openrouter.ai/api` and put the OpenRouter key
in `TYPESAFE_API_KEY`.

### Cloudflare

Set `cloudflareAccountId` (or `CLOUDFLARE_ACCOUNT_ID`). The client then treats
`apiKey` as a Cloudflare token (`CLOUDFLARE_API_TOKEN` when `apiKey` is
omitted), posts to
`https://api.cloudflare.com/client/v4/accounts/{id}/ai/run` as
`{ model: "typesafe/jev", input: { state, questions } }`, and unwraps the
Workers AI envelope to `{ model, answers, usage }`. TOML `model` and CLI
`--model` are not sent as the Cloudflare catalog id.

```ts
const client = new TypeSafeClient({
  apiKey: process.env.CLOUDFLARE_API_TOKEN,
  cloudflareAccountId: process.env.CLOUDFLARE_ACCOUNT_ID,
});
```

CLI: set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. Do not also set
`TYPESAFE_BASE_URL`. The token needs Account → Workers AI → Read. For
`--cache`, the CLI wraps Cloudflare inside `createCachingFetch` so cache keys
stay System One JSON. If you pass your own cache as `fetch`, wrap Cloudflare
inside it first; otherwise the client rejects the combination.

| Host | Model to send |
| --- | --- |
| `api.typesafe.ai` | `jev-1.13.0` / `jev-latest` |
| OpenRouter | `jev-1.13` or `typesafe/jev-1.13` |
| Cloudflare | catalog `typesafe/jev` (set by the client) |

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
stdin when `--state` is omitted. `--cache` reuses per-question answers from
`.systemoneprompts/cache`.

Each eval case has `state` and optional `id`, `labels`, and `factors`.
Labels are Choice strings, Noul Booleans, or integer Score levels.
`--sweep <factor>` compares thresholds.

CLI model precedence: `--model`, TOML `model`, `TYPESAFE_MODEL`,
`TYPESAFE_DEFAULT_MODEL`, then `jev-latest`. In Cloudflare mode `--model` does
not change the catalog id `typesafe/jev`; the reported `response.model` is
whatever Cloudflare returned.

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
Live tests require `TYPESAFE_API_KEY`:

```sh
sh scripts/run-quiet.sh "Live tests" -- bun run test:live
```

After release checks pass, `bun run release:publish` builds and publishes to npm.
