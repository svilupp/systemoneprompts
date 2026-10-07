# OpenAI Decisions backend

Exploration completed on 2026-10-07. Add an `OpenAIDecisionsClient` that accepts
the existing System One requests and returns the existing System One results.
Keep question shapes, generated evaluation code, required state, and factors
provider-independent; TOML may optionally select the REST backend.

The boundary is one client interface with swappable REST implementations.
Application code submits the same state and questions and consumes the same
normalized answers. Provider selection happens at construction; only the
adapter's endpoint, credentials, model default, and wire translation change.

Status: **implementation complete and verified on 2026-10-07**, including caching.
Both packages export the client and error type; both CLIs support TOML selection,
provider overrides, and OpenAI `--cache`. The existing canonical per-question
interceptor, hashes, record format, and miss splitting are reused. The private
inner adapter translates cache misses into Decisions requests. OpenAI records
have provider/version/base-URL scope; TypeSafe paths stay unchanged.

Both release suites passed, including packed consumers. Cross-runtime tests prove
that TypeScript and Python read each other's records and write byte-identical
records. Live tests in both runtimes verify all three question types followed by
identical cached answers with zero usage. Python checks use `UV_NO_CONFIG=1` to
avoid the global cutoff setting without changing the lockfile.

The seven-case labeled comparison is saved in
[docs/openai-decisions-sample.json](docs/openai-decisions-sample.json). It includes
both providers, missing facts, contradictory evidence, literal path references,
and instruction-like content. Unknown labels remain explicitly unknown.
Probability differences are observations, not production calibration guarantees.

The sections below document the design and completed implementation sequence.
Multimodal inputs, application calibration, representative performance benchmarks,
and captured live refusal examples remain the explicit scope limits below.

## Proposed usage

```toml
provider = "openai"
model = "gpt-6-luna"

[questions.duplicate_charge]
type = "noul"
instructions = "Does the customer report being charged twice?"
```

`provider` is optional. With it set, `run` and `eval` select the REST client
from the definition; `--provider` overrides it. Omitting it preserves the
existing TypeSafe path. `model` remains the existing independent model pin.

```ts
import { OpenAIDecisionsClient } from "systemoneprompts";
import { assertState, questions, evaluateFactors } from "./ticket.generated.js";

const client = new OpenAIDecisionsClient(); // OPENAI_API_KEY
assertState(state);
const result = await client.systemOne({ state, questions });
const factors = evaluateFactors(result.answers);
```

```python
from systemoneprompts import OpenAIDecisionsClient
from ticket_generated import assert_state, questions, evaluate_factors

assert_state(state)
client = OpenAIDecisionsClient()
try:
    result = await client.system_one(state=state, questions=questions)
    factors = evaluate_factors(result["answers"])
finally:
    client.close()
```

```sh
systemoneprompts run ticket.toml --state ticket.json --provider openai
systemoneprompts eval ticket.toml --cases cases.jsonl --provider openai
```

Definitions without a pinned model can run against either backend. A definition
with `model = "jev-latest"` needs an explicit `--model gpt-6-luna` override for
OpenAI. Never silently replace an author-pinned model.

## What the experiments established

The [official Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
and the pasted documentation agree: the beta uses `POST /v1/decisions` and
currently supports `gpt-6-luna`. This is the endpoint to integrate. Responses
with Structured Outputs would add a different generation and probability
contract without solving the compatibility work here.

Evidence is saved in
[tools/learning/openai-decisions-results.json](tools/learning/openai-decisions-results.json).
The report includes synthetic requests, responses, HTTP status, request IDs,
elapsed time, and normalized successful translations. It contains no API key.

| Probe | Observed result | Design consequence |
| --- | --- | --- |
| Mixed translated Noul, Choice, Score | 200; all three normalize | One shared-input request can contain independent questions |
| Structured instructions rendered to JSON text | 200 | Structured definitions require a documented text encoding |
| Object instructions sent directly | 400 `invalid_type` | Translate before sending |
| Missing predicate instructions | 400 `missing_required_parameter` | Supply a stable fallback or reject an empty question |
| Native predicate `criteria` | 400 `unknown_parameter` | Fold true/false criteria into predicate instructions |
| Duplicate names | 400 | Generate unique transport names and validate returned identity |
| Literal `__proto__.a[-1]` name | 200, echoed | Literal names work in this probe; full native-ID support is still broader |
| `jev-latest` | 404 `model_not_found` | Resolve provider defaults; let the API validate model availability |
| Null choice description | 400 `invalid_type` | Omit null descriptions |
| Single-option choice | 400 `array_below_min_length` | OpenAI compatibility check must require two options |
| Empty questions | 400 `empty_array` | Reject locally before transport |
| User message with `input_text` | 200 | Text-message input is supported, but not needed for the first client |
| Object choice description sent directly | 400 `invalid_type` | Render descriptions as text |

The recorded suite made 13 requests: four successful requests used 928 input
tokens and zero output tokens. Their elapsed times were 218, 220, 295, and
1,485 ms. A preceding mixed smoke request also succeeded in 1,827 ms with
397 input tokens. These are connectivity observations, not latency benchmarks.

Both package replays passed:

- Existing `partitionAnswers` / `partition_answers` accepts all normalized answers.
- Existing factors read the Noul probability, selected Choice, and fractional Score fields.
- The application ID `__proto__` survives the translation and existing factor evaluation.
- Offline synthetic cases preserve a score of `1.1` and the original structured legend.
- Offline synthetic cases reject refusal, missing/duplicate answers, invalid probabilities,
  missing distribution entries, and a fractional level index.

The live score happened to be `1.0`. Fractional-score preservation is established
by the documented contract and an offline specimen, not by that live result.
Refusal was tested synthetically; no live refusal was observed.

## Small abstractions

Expose one new client and reuse the existing structural client interface.
Keep protocol translation and HTTP mechanics private.

```text
application / generated definitions / patterns
  -> SystemOneClient.systemOne / system_one
  -> selected REST client with private provider adapter
       TypeSafe: POST /v1/systemone
       OpenAI:   POST /v1/decisions
  -> existing SystemOneResult shape
```

The construction site can swap `TypeSafeClient` for `OpenAIDecisionsClient`;
the request call, answer helpers, and factor evaluation stay the same. The CLI
factory performs that swap once from CLI override or TOML `provider`. Applications may inject
either compatible client into their existing functions and patterns.

Separate concrete client names preserve the existing API and keep provider
configuration explicit. They are implementations of the same interface, not
different application APIs. A common public facade can be added later if it
removes repeated construction code; it is not required for interchangeable
clients. Do not add provider checks to callers or orchestration helpers.

| Component | Responsibility | Public? |
| --- | --- | --- |
| `SystemOneClient` | Existing structural contract used by patterns in both languages | Keep current location and exports |
| `OpenAIDecisionsClient` | Credentials, provider default model, call options, lifecycle | Yes |
| `encodeDecisionsRequest` | State/question translation and a local answer-name lookup | No |
| `decodeDecisionsResponse` | Strict provider validation and native answer reconstruction | No |
| HTTP transport helper | Shared mechanics only where real duplication warrants extraction | No |

Use functions and composition. No plugin registry, provider base class, new
question hierarchy, `decide()` API, or OpenAI-specific factor vocabulary.
Python already defines a `SystemOneClient` protocol in `patterns.py`; TypeScript
already exports its structural interface from `/patterns`. Reuse both unchanged.

The client must preserve generic TypeScript inference:

```ts
class OpenAIDecisionsClient implements SystemOneClient {
  systemOne<const Q extends Questions>(
    request: SystemOneRequest<Q>,
    options?: SystemOneCallOptions,
  ): Promise<SystemOneResult<Q>>;
}
```

Support Python async `system_one` and explicit `close()`, matching the existing
client lifecycle. Defer new context-manager conveniences and sync methods until
needed. Injected HTTP clients/transports retain caller ownership.

## Request translation

The public input remains `{ state, questions, model? }`. The actual HTTP body is:

```json
{
  "model": "gpt-6-luna",
  "input": "{\"ticket\":{\"message\":\"I was charged twice\"}}",
  "questions": [
    {
      "type": "predicate",
      "name": "q0",
      "instructions": "Does `ticket.message` report two charges?"
    }
  ]
}
```

### State and descriptions

- String state passes through as text. All other JSON-compatible state values
  (objects, arrays, null, finite numbers, booleans) use canonical JSON text.
  Preserve arrays and literal keys; do not reinterpret primitive state.
- Validate JSON compatibility first. Reject cycles, dates, non-finite numbers,
  sparse arrays, and undefined values rather than coercing or dropping evidence.
- Nonempty string instructions and string descriptions pass through verbatim. Objects and arrays
  become compact canonical JSON strings. Never use language `repr` or `[object Object]`.
- Absent, null, blank-string, empty-object, and empty-array instructions use the
  fallback subject to the Noul restriction below. Null choice/score descriptions are omitted.
- Do not resolve or interpolate backticks. A path such as `ticket.message` stays
  in the instructions and refers to the serialized evidence. Deep indexed and
  wildcard path interpretation needs task evals before claiming semantic parity.
- `[data]` remains application-owned and is never sent automatically.

Use the existing canonical JSON helpers in both packages. Their existing tests
already cover JavaScript-compatible number spelling, Unicode, and key ordering.
The learning script's `json.dumps` renderer is not the implementation to promote.
Add adapter fixtures for those boundaries, including large Python integers:
the helper follows JavaScript number precision and must not be described as
a lossless encoding for arbitrary Python integers.

### Question mappings

| Native question | Decisions request |
| --- | --- |
| `noul` | `predicate`; same instruction text plus optional true/false rubric |
| `choice`, criteria map | `choice`; each key becomes a string `value`; each non-null description becomes text |
| `score`, criteria array | `score`; array position becomes a level; label is its decimal index; description is rendered criterion |

Predicate instruction rendering has a fixed format, versioned with the adapter:

```text
<original instruction, or fallback>
Outcome criteria (JSON): {"false":<criterion>,"true":<criterion>}
```

Only append criteria that exist. Preserve false criteria: dropping them changes
the question. The generic fallback is
`Evaluate the supplied evidence against the criteria.` Reject a Noul with both
absent/empty instructions and absent/empty outcome descriptions. Define empty
structurally (null, blank string, empty object or array); do not attempt semantic
validation of prose. Choice/Score can use the fallback because their alternatives
define the task.

Generate opaque names (`q0`, `q1`, ...) with a local name-to-literal-ID map.
This small lookup keeps arbitrary TOML IDs independent of provider name rules.
Decode by name, never array position or path parsing. Cache miss subsets create
their own maps. Use null-prototype maps or safe own-property writes in
TypeScript, including choice labels such as `__proto__` and `constructor`.

### Compatibility validation

Run the existing definition checks first, then an OpenAI-specific preflight.
Do not make valid TypeSafe definitions invalid globally.

- Require non-empty questions and string instructions after rendering.
- Require at least two Choice options. Do not add a fake alternative or invent
  a deterministic answer/confidence for single-option definitions.
- Keep at least two ordered Score levels and the existing Choice-only 255-label cap.
- Require a nonblank model, defaulting to the model tested here. Pass explicit
  model strings through to the API; availability is a server concern, not a
  package allowlist. Reject an explicitly supplied blank constructor/request/CLI
  model before resolution; omission selects the default. A cached result is a
  prior observation, not a live access check.
- Report question ID and a stable code, e.g. `openai-choice-min-options`,
  `openai-question-empty`, or `openai-model-empty`.
- Verify API upper limits during implementation. The guide and these probes do
  not establish full question-count, option-count, text-size, or image limits.
  Do not silently truncate or split a request at guessed limits.

## Response translation and failures

| Decisions answer | Existing result |
| --- | --- |
| Predicate `probability` | `{ type: "noul", noul: probability }` |
| Choice `choice`, probability array, `confidence` | Existing Choice, probabilities keyed by original string values |
| Score expected value, probability array, `confidence` | Existing Score; probabilities keyed by decimal indices; legend from original criteria |
| Refusal | Whole-call error with refused IDs and raw response for inspection |

Preserve Score expected values, including fractions. Do not choose the most
likely level or round the score. Reconstruct the legend from original criteria,
not numeric labels echoed by OpenAI; structured descriptions must survive.
Copy confidence as supplied. It is a distinct field and is not synthesized
from the winning probability.

Validate the entire response before exposing a successful `SystemOneResult`:

1. Require a model string and answers array. For this new backend in both
   languages, require nonnegative integer `input_tokens` and `output_tokens`;
   reject booleans, null, and missing counts. Ignore extra usage fields. This
   gives the normalized result one shared contract.
2. Require exactly one answer per requested name; reject duplicates, missing
   names, unknown names, and mismatched types. Accept any answer ordering.
3. Require finite probabilities/confidence in `[0,1]`. Require every requested
   Choice value or Score index exactly once and no extras.
4. Require finite Score in `[0, levels.length - 1]`, integer probability indices,
   and a Choice selected from the original labels.
5. Preserve probabilities as returned. Do not enforce the learning script's
   guessed `0.02` sum tolerance or recompute confidence/Score from rounded values.
6. Preserve reported usage, including zero output tokens. Reject missing or
   invalid required counts; do not replace unavailable usage with fabricated zeroes.

Use one `OpenAIDecisionsError` with a discriminant such as `kind` (`http`,
`transport`, `timeout`, `response`, `refusal`, `compatibility`). Include relevant
fields: HTTP status, request ID, retry-after, refused IDs. Avoid a new class per
failure kind. A refusal never becomes Noul `0.5`, Choice confidence `0`, or a
missing successful result. Retain the raw response on the error for inspection;
defer a public partial-answer API.

Whole-call failure keeps the existing typed result honest. `eval` records a
failed case and preserves its report; `runMany` returns its existing per-item
error. A future partial-success API can be additive if needed.

TypeSafe error classes and their existing `instanceof` behavior stay intact.
If shared transport extraction becomes necessary, pass an explicit error
factory/terminal-error policy; do not rename public TypeSafe errors or rely on
OpenAI errors inheriting from TypeSafe errors.
Adapter validation, refusal, and read-only cache misses are terminal errors,
not network failures to retry.

## Transport and cache

Reuse global fetch in TypeScript and `httpx2` in Python. A direct REST adapter
fits the repository and avoids new SDK dependencies. The guide lists SDK
minimums if SDK adoption becomes useful later; SDK adoption is not required here.

### First delivery: direct HTTP

Call `/v1/decisions` directly. `fetch` in TypeScript and transport/http-client
injection in Python always mean raw network I/O. Keep endpoint, headers,
encoding, HTTP execution, and decoding explicit inside the new client. Decode
a successful response outside the network retry loop so refusal or malformed
output cannot be retried as a connection failure.

Reuse existing small utilities where practical. Extract shared HTTP mechanics
only when implementing both call paths demonstrates concrete duplication;
do not make a transport framework or TypeSafe refactor a prerequisite.
TypeSafe defaults and errors remain unchanged. Start OpenAI with matching
10-second per-attempt timeout and two retries. Use bounded Retry-After and
retry only 408/429/5xx and transient transport failures. Adapter/refusal errors
are terminal. Preserve `x-request-id`; caller cancellation must stop retries.

The core client keeps raw HTTP injection. The completed dev factory and CLI
support `--provider openai --cache` through the canonical cache interceptor.

### Completed cache support

Keep the existing cache as a transport interceptor. It recognizes only
`/v1/systemone` and sees `{state, questions, actual model}`. OpenAI support can
reuse that envelope privately, with normalization inside the cache, following
the Cloudflare precedent. Avoid a general cache rewrite.

```text
dev factory creates cached OpenAI client
  -> canonical request through existing cache
  -> private Decisions adapter
  -> POST /v1/decisions
  -> native normalization before cache write
  -> final native validation after cache/live merge
```

A dev-only `createCachedOpenAIDecisionsClient({ client, dir?, mode? })` returns
`{ client, cache }` and owns adapter ordering and directory selection. CLI
construction calls it. `client.fetch` remains raw network injection. Keep the
core constructor cache-free. Reject a bare caching fetch passed as raw network
transport rather than silently bypassing its behavior. No public adapter API
is needed until callers demonstrate a composition use case.

Preserve existing cache records and hashes. A proposed namespace is:

```text
.systemoneprompts/providers/openai-decisions/v1/<base-url-hash>/cache/
```

`dir` is a root under which the factory adds provider, adapter version, and
normalized base-URL scope. Never include credentials. End the resolved path in
`cache`, matching Python's current clearing guard. Keep existing TypeSafe paths
unchanged. Bump the adapter version when rendering or normalization changes.

Cache management is part of this delivery: current stats walk only one shard
level, while clearing is recursive. Add provider-aware stats/clear resolution
using the same directory resolver as run/eval. Defaults continue to address
TypeSafe only. Do not hide OpenAI records from stats while allowing a default
clear to delete them. Define how a custom cache root is resolved consistently.

Current cached-answer validators check finite values but do not enforce all
OpenAI constraints. Validate the final merged result using the same normalized
answer validator as live decoding; a hit must not bypass range, label, or
legend checks. If invalid entries must become misses rather than errors, add
one optional entry-validator callback to the existing cache, keeping its default
behavior unchanged. Decide this before shipping cache support.

Require cross-language directory/record parity, all-hit zero usage, miss
splitting, read-only behavior, version/origin isolation, and terminal errors.
Write no entries from a refused or malformed whole response in the first
cached version.

## Configuration and CLI

| Setting | Proposed rule |
| --- | --- |
| Client selection | Explicit `new OpenAIDecisionsClient()` |
| Provider precedence | `--provider` / explicit construction override > TOML `provider` > existing TypeSafe path |
| Default provider | Existing TypeSafe path, including current OpenRouter/Cloudflare behavior |
| Key | Explicit `apiKey` / `api_key`, otherwise `OPENAI_API_KEY` |
| Base URL | Constructor option, otherwise `https://api.openai.com/v1`; defer another environment fallback |
| Default model | `gpt-6-luna` |
| CLI model precedence | Provider default < TOML model < `--model`; defer another model environment variable |
| Programmatic model precedence | Provider default < constructor default < request model |
| Timeout/retries/injection | Same option conventions as existing client, with provider-specific diagnostics |

Normalize trailing slashes and append `/decisions` exactly once. Do not reuse
`TYPESAFE_BASE_URL`, `TYPESAFE_MODEL`, or Cloudflare credentials in OpenAI mode.
Unrelated environment variables do not select a provider. Only keys selected
for that provider are sent to its transport. Unknown provider values fail
locally. Explicit incompatible constructor options fail locally as well.

### TOML selection

Recognize an optional top-level scalar `provider = "typesafe" | "openai"`,
alongside the existing `model`. Keep the configuration flat; a new table is
unnecessary for these two settings. Reject blank, non-string, and unsupported
provider values with a positioned diagnostic during offline checking.

Parse it as `Definition.provider` in both languages. Preserve its existing
scalar metadata representation (`meta.provider`) for compatibility with
consumers that already inspect metadata. Treat reserving this previously
application-owned scalar as a documented compatibility change; include fixtures
for existing definitions without it and definitions using an invalid value.

Generation preserves the selection in `meta.provider`. No new generated export
is necessary: `meta.provider` and the existing `model` export are sufficient
construction hints. Generated modules do not instantiate clients, read keys,
or make requests. Applications using an explicitly constructed concrete client
keep that choice; consuming TOML selection happens in the construction factory,
not inside `systemOne` / `system_one`.

The existing CLI factories consume `definition.provider` unless `--provider`
is present. Resolve provider first, then that provider's model default and key.
An override changes provider selection only; it does not discard an explicit
TOML model. For example, overriding a TypeSafe definition to OpenAI may also
require `--model gpt-6-luna`. An invalid TOML provider still fails checking even
if a CLI override is supplied.

Keep API keys in the environment or explicit constructor options. Never put
credentials in TOML, generated metadata, request bodies, or cache identity.
The first TOML surface covers provider and model; transport settings retain
their constructor options rather than introducing an unrestricted config bag.

`check` and `generate` stay offline. They validate provider configuration without
constructing a client or requiring credentials. `run` and `eval` validate definitions,
state, cases, sweep/report options, and provider compatibility before sending.
OpenAI mode must not ask for `TYPESAFE_API_KEY`. Existing Python `run --answers`
continues to work offline.

Use existing model helpers unchanged. TypeScript already supports
`resolveModel("gpt-6-luna", def.model, options.model)`; Python already accepts
an explicit `default`. Resolve the actual model before any future cache lookup.
Generated `model` exports stay author metadata, not provider inference.

## Implementation sequence

### 1. Codec and TypeScript client

- Add private request/response mapping functions and `OpenAIDecisionsClient` in
  `src/openai-decisions.ts`. Split files only when size warrants it.
- Keep `SystemOneClient` in its existing location. Export the new client and
  single error type through `src/index.ts`; update public API checks.
- Put provider JSON fixture pairs in `conformance/v1/providers/` and load them
  directly from focused adapter tests in both packages. Sync both package copies
  with `tools/sync-shared.py`. Keep them outside the definition-case manifest;
  a new wire protocol does not require new TOML case-runner machinery.
- Test generic result inference, structured criteria, literal IDs, absent/null
  fields, response ordering, refusal, and malformed answers.

### 2. Python parity and CLI

- Add `systemoneprompts/openai_decisions.py`, export via `__init__.py`, and match
  the fixture outputs and diagnostics. Reuse the existing client protocol,
  HTTP injection conventions, JSON helpers, and `close()` ownership rules.
- Update TypeScript `src/cli/{index,io,run,eval}.ts` and Python `cli.py` /
  `provider.py` for explicit selection and a structural client return type.
- Extend both definition parsers/types with optional `provider`, preserve
  `meta.provider`, and resolve CLI override > TOML > default in their factories.
- Update SPEC and compatibility notes for the reserved scalar and diagnostics.
  Add shared fixtures for valid/invalid values, omitted defaults, metadata
  generation, and override precedence; synchronize both package copies.
- Keep existing provider paths intact. Support OpenAI `--cache` through the dev factory.
- Add package examples and compatibility documentation. Definitions without
  `provider` keep byte-identical generated output; selected providers remain
  metadata and do not change emitted questions, assertions, or factors.

### 3. Verify the first delivery

- Run both package quiet checks and mocked packed npm/wheel consumer checks.
- Add explicit opt-in live smoke tests requiring only `OPENAI_API_KEY`.
- Run a small labeled sample for all three answer types and report probability
  differences. Production threshold tuning remains application work; a large
  comparative benchmark is not a prerequisite for an opt-in client release.
- Add shared conformance cases only for changed native behavior; when added,
  synchronize root and both package copies with `tools/sync-shared.py`.

### 4. Complete caching

- Implement the dev factory, private canonical transport adapter, directory
  resolver, provider-aware cache management, and final merged validation together.
- Test both runtimes reading each other's records plus existing provider
  regression suites. Document the factory as the supported caching entry point.
- Enable OpenAI `--cache` only after those checks pass.

## Acceptance checks

- Existing definitions without the newly reserved `provider` setting produce
  byte-identical generated modules before and after the change.
- TOML `provider` selects the same client as the corresponding CLI flag; CLI
  overrides TOML and omission preserves existing behavior. Invalid selection
  fails offline, while valid selection never requires keys during generation.
- Both clients work with `runMany` and `walkTaxonomy` without provider branches.
- One consumer test runs the same request and result-processing code against
  both mocked REST clients, changing only client construction. Assert the actual
  provider routes and the same normalized result contract.
- TypeScript preserves exact Choice label types and Score legends.
- Structured state, instructions, and criteria survive text encoding; `[data]`
  does not appear in outgoing requests unless the application puts it in state.
- Invalid CLI state, blank model, and single-option Choice make zero requests.
  OpenAI all-hit `--cache` also makes zero requests. Arbitrary nonblank model availability is checked by the API.
- Missing, duplicate, unexpected, malformed, and refused answers cannot become
  successful typed results; provider responses remain inspectable on errors.
- The cache covers all hits, partial/read-only misses, malformed
  records, stats/clear scope, final validation, version/base-URL isolation, and
  TypeSafe/OpenAI separation.
- HTTP tests cover authorization ownership, `x-request-id`, the actual
  `/v1/decisions` route, retry-after, non-retryable 4xx, cancellation, and timeout cleanup.
- Existing TypeSafe/OpenRouter/Cloudflare suites and public APIs remain valid.

## Reproduce the learning tests

The supplied key is saved only in the ignored root `.env` with mode `0600`.
The learning runner loads `OPENAI_API_KEY` from the environment or that file.
No dependency, lockfile, or production source change was needed.

From `packages/python`:

```sh
sh scripts/run-quiet.sh "OpenAI offline learning" -- python3 ../../tools/learning/openai_decisions.py
sh scripts/run-quiet.sh "OpenAI live learning" -- python3 ../../tools/learning/openai_decisions.py --live
sh scripts/run-quiet.sh "OpenAI Python replay" -- .venv/bin/python ../../tools/learning/verify_openai.py
```

From `packages/typescript`:

```sh
sh scripts/run-quiet.sh "OpenAI TypeScript replay" -- bun ../../tools/learning/verify-openai.ts
```

The live runner sends at most 13 synthetic requests, without retries, and saves
the report after each completed call. It stops on authentication, access,
rate-limit, or network failure. Expected 400/404 probes are successful learning
checks, not evidence of an unavailable endpoint.

The Python replay used the existing virtualenv: `uv run --locked` was blocked
by a global exclude-newer setting that would require lockfile resolution.
The lockfile was left unchanged. Both replays test the recorded normalized
result, not a production OpenAI client.

## Remaining work and scope limits

- **Calibration:** one predicate produced `0.67` in the initial smoke and `0.86`
  with additional criteria in the recorded suite. Wording and rubric differences
  matter; do not assert TypeSafe-equivalent probabilities from these toy tests.
- **Limits:** the official API reference was checked on 2026-10-07. It lists
  text field length bounds but no upper question/option/level counts. Server
  errors remain inspectable; no guessed truncation or splitting is introduced.
- **Ambiguous evidence:** seven labeled sample cases now include missing facts,
  contradictory state, path references, and instruction-like application content.
  Missing and contradictory binary labels are explicitly unknown.
- **Images:** the guide supports inline base64 image data URLs. Ordinary state
  currently has no image contract. Defer multimodal input to an explicit additive
  API; do not reinterpret arbitrary state objects as OpenAI messages or images.
- **Refusal:** add captured provider refusal fixtures when available; keep
  deterministic synthetic coverage until then.
- **Beta evolution:** recheck official request/response schemas before implementation
  and bump the adapter/cache namespace when translation behavior changes.
- **Performance:** a sequential 21-call-per-provider benchmark now records latency,
  usage, and list-price estimates in [docs/provider-benchmark.md](docs/provider-benchmark.md).
  It repeats seven short synthetic cases, so representative production batches
  are still needed before choosing latency budgets. The guide's speed claim
  against Responses was not tested.
