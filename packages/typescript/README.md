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

```ts
const client = new TypeSafeClient(); // TYPESAFE_API_KEY
```

### Legacy Cloudflare Jev

In TypeSafe mode, `CLOUDFLARE_ACCOUNT_ID` selects this route even when
`TYPESAFE_API_KEY` is also set. Unset the account ID to call native TypeSafe.
Explicit OpenAI, OpenRouter, and Clef/Flash providers ignore this legacy switch.

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

```ts
import { TypeSafeClient } from "systemoneprompts";
import { createCachingFetch, openRouterCacheDir } from "systemoneprompts/dev";

const cache = createCachingFetch({ dir: openRouterCacheDir() });
const client = new TypeSafeClient({
  provider: "openrouter",
  defaultModel: "openai/gpt-6-luna-decisions", // omit for Jev Latest
  // apiKey: process.env.OPENROUTER_API_KEY,
  // baseURL: "https://openrouter.ai/api/alpha",
  fetch: cache,
});
const result = await client.systemOne({
  state: { message: "Help! My payouts have been failing for 3 days." },
  questions: { urgent: { type: "noul", instructions: "Is this urgent?" } },
});
console.log(result.answers.urgent.noul);
```

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

```ts
import { OpenAIDecisionsClient } from "systemoneprompts";
const client = new OpenAIDecisionsClient();
const result = await client.systemOne({
  state: "I was charged twice.",
  questions: { duplicate: { type: "noul", instructions: "Was the customer charged twice?" } },
});
console.log(result.answers.duplicate.noul);
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

```ts
import { OpenAIDecisionsClient } from "systemoneprompts";
import { createCachedOpenAIDecisionsClient } from "systemoneprompts/dev";

const network = new OpenAIDecisionsClient();
const { client, cache } = createCachedOpenAIDecisionsClient({
  client: network, mode: "read-write", // also read-only or refresh
});
// Use client.systemOne({state, questions}) as usual.
console.log(cache.dir, cache.stats());
```

Use the dev factory for caching; passing a bare cache as raw network injection
is rejected because it would bypass canonical request interception.

### Cloudflare Clef and Clef Flash

Set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. The CLI reads `.env` in
the current working directory; programmatic clients read the process environment.
See [example 12](examples/12-cloudflare-decisions/README.md) for repository-root setup. Select `provider = "cloudflare"`
and `model = "clef"` or `"clef-flash"` in TOML, or pass `--provider cloudflare --model clef-flash`.
Full `@cf/cloudflare/` catalog IDs are accepted and canonicalized.

```ts
import { CloudflareDecisionsClient } from "systemoneprompts";
import { createCachedCloudflareDecisionsClient } from "systemoneprompts/dev";

const network = new CloudflareDecisionsClient({ defaultModel: "clef-flash" });
const { client } = createCachedCloudflareDecisionsClient({ client: network });
const result = await client.systemOne({
  state: { message: "The service is down for all customers." },
  questions: { urgent: { type: "noul", instructions: "Is this an outage?" } },
});
console.log(result.answers.urgent.noul);
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
