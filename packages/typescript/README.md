# systemoneprompts

This is the primary TypeScript package in the multi-language systemoneprompts repository. It is self-contained under `packages/typescript/`: install dependencies here, run its scripts here, and release the npm archive produced here. The language-neutral contract and migration plan live one directory above in `../../docs/` and `../../PLAN_packages.md` when working from the repository.

TOML decision definitions for System One. [TypeSafe](https://docs.typesafe.ai) / JEV are providers. One `.toml` file holds a complete semantic judgment — metadata, minimum state guarantees, **native TypeSafe question objects**, and tiny Boolean factors — and compiles to ordinary typed TypeScript. Live calls go through `TypeSafeClient`, a small `fetch` client for the TypeSafe System One API.

```text
application state
      ↓  assertState()          minimum guarantees, never reshapes
TypeSafe questions              exact API objects, generated from TOML
      ↓  client.systemOne()     TypeSafeClient, or any object with the same method
TypeSafe answers
      ↓  evaluateFactors()      Boolean derivations, one line of TOML each
ordinary application code decides what happens
```

Someone who has read the TypeSafe docs learns two new concepts: `[requires]` and `[factors]`. Everything under `[questions]` uses TypeSafe's own field names and shapes.

Agents authoring definitions or integrating the package can load
[`docs/skills/systemoneprompts/SKILL.md`](docs/skills/systemoneprompts/SKILL.md). It covers
usage, domain organization, and TOML authoring, and is included in the npm package.

## Quick start

```sh
npm install systemoneprompts
# Node ≥ 20, or Bun
```

```toml
# triage.toml
title = "Support ticket triage"
version = "0.1.0"
model = "jev-latest"

[requires]
"ticket.message" = "string"

[questions.topic]
type = "choice"
instructions = "Which team should handle `ticket.message`?"

[questions.topic.criteria]
billing = "Charges, invoices, refunds"
orders = "Shipments and deliveries"

[factors]
"topic.billing" = { ref = "topic", choice = "billing" }
```

```sh
npx systemoneprompts generate triage.toml
```

```ts
import { TypeSafeClient } from "systemoneprompts";
import { questions, model, assertState, evaluateFactors } from "./triage.generated.js";

assertState(state); // throws naming the path; narrows `state` to RequiredState
const response = await new TypeSafeClient().systemOne({ state, questions, model });
const factors = evaluateFactors(response.answers);
if (factors["topic.billing"]) routeToBilling(ticket);
```

`response.answers.topic.choice` is typed as `"billing" | "orders"` from the question criteria; `factors` is typed by the generated `Factors` interface.

## File format

| Key | Kind | Purpose |
| --- | --- | --- |
| `title`, `version`, `description` | scalars | Human metadata (`version` is the definition's version) |
| `model` | scalar | Optional model pin passed to `systemOne`. Omit it and `TypeSafeClient` uses `TYPESAFE_DEFAULT_MODEL`, then `jev-latest`. |
| `[requires]` | table | Minimum state guarantees |
| `[questions]` | table | Exact TypeSafe question objects |
| `[factors]` | table | Local Boolean derivations |
| `[data]` | optional table | Application-owned JSON-compatible data, preserved and exported verbatim |
| any other scalar | — | Preserved in `definition.meta` |
| any other table | — | Warning (`[question]` → did you mean `[questions]`?) |

### `[requires]`

```toml
[requires]
"ticket.message" = "string"
"support.tickets[0].message" = "string"
"messages[].text" = "string"
"metadata.legacy" = "exists"
```

Vocabulary: `string | number | boolean | array | object | null | exists`. Extra fields pass. `assertState(state)` narrows and **returns nothing** — the original object is what `systemOne` receives. A scalar path that is a prefix of another (`"ticket" = "string"` next to `"ticket.message"`) is a compile error.

Explicit `object` and `array` requirements validate JSON-compatible contents recursively, rejecting values such as dates, maps, undefined, and cycles. `exists` checks presence only.

Container requirements must also agree: `ticket.message` needs an object, and `tickets[0]` needs an array. Paths use own properties; inherited values do not satisfy requirements. Nested indexes such as `matrix[0][0]` are supported. Generated array element types describe indexed and `[]` requirements. Runtime `[n]` checks that index only; `[]` checks every element.

Backticked path-like tokens in `instructions` and `criteria` are linted against `[requires]`; a prefix of a guaranteed path (`` `ticket` `` when `ticket.message` is required) counts as guaranteed. Mismatches are warnings with a nearest-match hint (`--strict` promotes them).

### `[data]`

`[data]` is an optional application-owned namespace. Its root is a TOML table;
its descendants may be any JSON-compatible nested objects, arrays, strings,
booleans and finite numbers. Generated modules export the parsed tree as
`data`. systemoneprompts does not interpret child keys, render templates, resolve
references, send data to TypeSafe, or validate an application's schema. Keep
runtime facts, state transitions and execution in application code. See the
[package skill](docs/skills/systemoneprompts/SKILL.md) for authoring conventions.

### `[questions]`

Three types, TypeSafe's names, no aliases. `instructions` and every criteria entry may be a string, table, or array — forwarded verbatim.

A definition must contain at least one question. Descriptions must contain JSON-compatible values; quote TOML dates and times to use them as text.

```toml
[questions.topic]
type = "choice"
instructions.question = "Which team should handle `ticket.message`?"

[questions.topic.criteria.billing]
what = "Charges, invoices, refunds"
not_for = "Order tracking"

[questions.is_urgent]
type = "noul"
instructions = "Does this convey urgency?"

[questions.frustration]
type = "score"
instructions = "How frustrated is the customer?"
criteria = ["Calm", "Frustrated", "Very angry"]
```

Question IDs are literal strings. Quoted keys allow dots (`"spam.requests_credentials"`).

### `[factors]`

Every factor is a Boolean.

```toml
[factors]
"spam.corroborated" = { at_least = 2, of = ["a", "b", "c"] }
ready               = { all = ["topic.orders", "refund.strong"] }
underspecified      = { not = "requirements_clear" }
"topic.billing"     = { ref = "topic", choice = "billing" }
"refund.strong"     = { ref = "refund_requested", noul = { gte = 0.7 } }
"refund.known"      = { ref = "refund_requested", known = true }
"step_up"           = { ref = "refund_requested", known = true, noul = { gte = 0.5 } }
"gray"              = { ref = "x", noul = { gt = 0.4, lt = 0.6 } }
```

A bare Noul in `all` / `any` / `not` / `of` means `noul >= 0.5`. Choice and Score IDs must pass through a predicate. Each factor uses exactly one of `ref` / `all` / `any` / `not` / `at_least`. Missing answers at runtime are errors, never `false`, unless the predicate uses `known` (see below).

Fields are checked for the selected operator: `of` belongs only to `at_least`, and `choice` / `noul` / `score` / `confidence` / `known` belong only to a `ref` predicate. Numeric comparators must be finite. Boolean operators validate every referenced answer, even when an earlier answer already determines the result.

`known = true` is true only for a present, usable answer. Explicit `missing`, Choice/Score `confidence = 0`, and a Noul of exactly `0.5` (when the answer has no `confidence` field) are unknown. Combine it with a comparator when unknown must not fire: `{ ref = "x", known = true, noul = { gte = 0.5 } }`. A `known`-only predicate treats a missing answer as unknown (`known = true` → false) instead of throwing.

Compile-time diagnostics carry file, line, and a hint:

```text
error: triage.toml:88  factor `topic.billing` references Choice `topic` with unknown option `billling`
                       available: billing, orders, account
error: triage.toml:90  Score `frustration` used directly in `all`; wrap it in a predicate: { ref = "frustration", score = { gte = … } }
```

## API

```ts
import {
  parseDefinition, loadDefinition, checkDefinition,   // TOML → Definition → Diagnostic[]
  createStateAssert, createFactorEvaluator,          // runtime pieces the generated code uses
  generate,                                          // Definition → *.generated.ts text
  TypeSafeClient,                                         // fetch client for TypeSafe System One
  SystemOnePromptsError, hasErrors, formatDiagnostic,
} from "systemoneprompts";
import { createCachingFetch } from "systemoneprompts/dev";
import { runMany, walkTaxonomy } from "systemoneprompts/patterns";
```

| Function | Role |
| --- | --- |
| `parseDefinition(toml, { filename })` / `loadDefinition(path)` | TOML → `Definition`. Throws `SystemOnePromptsError` only for invalid TOML; structural problems go to `definition.diagnostics` |
| `checkDefinition(def)` | every diagnostic: structural ones plus references, primitive compatibility, cycles, `[requires]` conflicts, backtick lint |
| `createStateAssert(def.requires)` | `(state) => asserts state is T`; never copies |
| `createFactorEvaluator(def.factorDefinitions)` | `(answers) => factors`; pure, throws on missing answers |
| `generate(toml, { filename })` | deterministic `*.generated.ts`; throws `SystemOnePromptsError` listing every error |
| `TypeSafeClient` | TypeSafe System One HTTP client (`fetch`, `timeout`, `apiKey`) |
| `createCachingFetch({ dir, mode })` | per-question `fetch` for `new TypeSafeClient({ fetch })`; `.stats()` is cumulative |
| `runMany(client, { questions, states, concurrency })` | same questions over many states; results keep order and are typed by `questions` |
| `walkTaxonomy(client, { state, tree, beamWidth })` | hierarchical Choice, best paths found by approximate beam search |

`Definition` exposes `meta`, `model`, `requires`, `questions` (native System One objects), `factors` (parsed), `factorDefinitions` (verbatim, for the evaluator), `diagnostics`, and `source`.

`TypeSafeClient` is the TypeSafe System One adapter. Pass `fetch` or `timeout` when you need different transport behaviour. Patterns take any object with `systemOne`.

`concurrency` and `beamWidth` must be positive integers. `runMany` collects request errors per state; an exception from `onResult` rejects the batch, and the callback is never retried.

## CLI

```text
systemoneprompts check    <files...> [--strict]
systemoneprompts generate <files...> [--out dir] [--check]
systemoneprompts run      <file> --state s.json | <stdin> [--cache] [--json] [--model name]
systemoneprompts eval     <file> --cases cases.jsonl [--cache] [--sweep factor] [--report out.json] [--model name]
systemoneprompts cache    stats | clear
```

`generate --check` fails in CI when generated files are stale. `run --cache` stores per-question answers under `.systemoneprompts/cache`; a second run of the same file and state spends zero tokens, and editing one question re-asks only that one.

`check` and `generate` report errors across all input files. Generation requires `.toml` inputs and rejects colliding output paths. Cache files are written atomically; malformed entries are treated as misses (and fail in read-only mode).

`eval` reads one JSON case per line — `{ "id", "state", "labels": { question: expected }, "factors": { factor: bool } }` — and reports per-question accuracy and confusion, per-factor accuracy, answers near a decision boundary, and with `--sweep <factor>` the accuracy of a predicate factor across thresholds (ground truth is `factors[<factor>]`, or a Boolean label on the referenced Noul).

Case labels must name existing questions and use Choice labels, Noul Booleans, or integer Score levels. Expected factors must name existing factors and be Booleans. Invalid cases and sweep requests fail before API calls; execution errors retain a partial report and return a nonzero exit status.

**Model selection.** The TOML `model` is a pin passed to `systemOne`; omit it and `TypeSafeClient` uses `TYPESAFE_DEFAULT_MODEL`, then `jev-latest`. Generated files always export `model` (typed `string | undefined`) so imports stay stable. Application code overrides it at the call: `systemOne({ state, questions, model: "jev-2026-06" })`. The CLI adds `--model`, which beats the TOML, which beats `TYPESAFE_MODEL` / `TYPESAFE_DEFAULT_MODEL`.

## Examples

See [`examples/`](examples/). 01–07 reproduce the unique blocks on TypeSafe's how-to-build page. 08–10 exercise `walkTaxonomy` and `runMany`. Examples import `systemoneprompts` straight from `src/` via `tsconfig.json` `paths`, so no build step is needed.

```bash
bun run examples/07-ticket-triage/run.ts
```

## Development

```bash
bun install
bun run check              # quiet named legs: typecheck, lint, tests, fitness, conformance, examples, API
bun run test:unit          # deterministic tests only
bun run test:fitness       # package boundary checks
bun run test:conformance   # local contract fixtures
bun run test:package       # pack and test the actual npm archive in a clean consumer
bun run release:check      # all checks plus package archive validation
bun run examples:generate  # after editing any examples/*/*.toml
bun run test:live          # explicit live tests; needs TYPESAFE_API_KEY
bun run build              # clean dist/ for publishing
```

`bun run check` never uses the live TypeSafe API. Full output from every check leg is retained in a temporary log; failed legs print their diagnostics. Run one named leg with `node scripts/check.mjs "Typecheck"`.

For release preparation, update the package version with `bun run release:prepare -- --version <version>`, run `bun run release:check`, and inspect the archive. `bun run release:publish -- --artifact <systemoneprompts-version.tgz>` is a dry run unless `--execute` is explicitly supplied by the release workflow.
