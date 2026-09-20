---
name: systemoneprompts
description: "Use the systemoneprompts TypeScript package to author System One TOML decision definitions, validate and generate modules, integrate native TypeSafe questions, and evaluate decisions. Includes domain organization and application-data authoring guidance. Use for systemoneprompts package work, not generic TypeSafe prompting without this package."
---

# Using systemoneprompts

systemoneprompts turns System One TOML decision definitions into native TypeSafe questions,
minimum state assertions and Boolean factors. Application code calls the
provider and decides what happens. Keep that boundary visible.

## Establish the supported contract

Read the package documentation before choosing an API or CLI option:

- [Package README](../../../README.md) for APIs, CLI options and examples.
- [Shared specification](../../SPEC.html) for format and semantic details.
- [Application-data layout](references/application-data.md) when organizing
  copy, labels and examples beside domain questions.

Check the installed package version when it differs from this checkout.

Structured `[data]` is implemented in this package. It is an arbitrary,
JSON-compatible application-owned tree beneath a TOML table root. The package
preserves and exports it; it does not assign child-key semantics, render it,
send it to the provider, or validate an application's schema. For older
installed versions, verify support before using `definition.data` or a
generated `data` export.

## Author a definition

Use native question fields: `type`, `instructions`, `criteria`. Define at least
one question. Use `noul` for a yes/no judgment, `choice` for a categorical
selection, and `score` for an ordered magnitude. Instructions and criteria
entries may contain strings, objects or arrays; they are forwarded to the
provider, so application-only metadata does not belong there.

```toml
title = "Support topic"

[requires]
"message" = "string"

[questions.topic]
type = "choice"
instructions = "Which topic best describes `message`?"

[questions.topic.criteria]
delivery = "Shipment tracking, delivery timing, or a missing parcel."
billing = "Charges, invoices, or payment failures; excludes shipment tracking."
other = "The request fits neither topic, or its topic is unspecified."

[factors]
is_delivery = { ref = "topic", choice = "delivery" }
```

Define one clear judgment per question. Explain neighboring boundaries rather
than relying on labels or examples alone. Structured criteria such as
`{ what = "...", not_for = "...", examples = [...] }` are ordinary author-chosen
payloads, not extra question fields or a phrase-matching grammar.

Use `[requires]` for the minimum evidence the questions need. Supported types
are `string`, `number`, `boolean`, `array`, `object`, `null` and `exists`.
Quote dotted or indexed paths, such as `"customer.orders[0].id"`; `"messages[].text"` requires every element's `text`. Assertions
check the supplied state; they neither transform it nor remove extra fields.
Build an appropriate provider state explicitly in application code.

Question and factor IDs are literal keys. A dotted ID is not a nested path:
quote it when authoring one. Do not give a question and factor the same ID.
Quote date/time values intended as strings and avoid non-finite numbers.

## Check, generate and integrate

1. Validate the definition before provider calls. `checkDefinition` returns
   diagnostics for structural and cross-reference problems;
   parsing successfully does not mean a definition is valid. Fix errors and
   inspect warnings. `--strict` makes warnings errors when that is appropriate
   for the project.
2. Generate the module using the package CLI, or load and validate definitions
   at runtime using its API. Do not hand-edit generated files.
3. Assert state, call `TypeSafeClient.systemOne` (or Python
   `TypeSafeClient.system_one`), and evaluate factors against its answers.
   Application code owns thresholds, routing and side effects.
4. After source changes, regenerate checked-in output and use `generate --check`
   to detect stale artifacts. Follow the target package's output-path options.

TypeScript consumer commands:

```sh
npm install systemoneprompts
# or: bun add systemoneprompts
npx systemoneprompts check support.toml --strict
npx systemoneprompts generate support.toml
npx systemoneprompts generate support.toml --check
# bunx systemoneprompts works the same way
```

Generated-module usage; executing the provider call requires live credentials:

```ts
import { TypeSafeClient } from "systemoneprompts";
import {
  assertState, questions, model, evaluateFactors,
} from "./support.generated.js";

const state = { message: "Where is my parcel?" };
assertState(state);
const response = await new TypeSafeClient().systemOne({ state, questions, model });
const factors = evaluateFactors(response.answers);
// Application code consumes factors.is_delivery and the underlying answers.
```

`assertState` returns nothing; do not assign its result to state. For an
offline answer check, call the generated `evaluateFactors` with supplied
answers. The TypeScript CLI has no `run --answers` option.

Live `run` and `eval` build `{ state, questions, model }`. Native TypeSafe uses
`TYPESAFE_API_KEY`. OpenRouter is the same client with
`baseURL: "https://openrouter.ai/api"`; pass the OpenRouter key as `apiKey`, or
put it in `TYPESAFE_API_KEY` for CLI. There is no `OPENROUTER_API_KEY`
integration. Cloudflare Workers AI is the same client with
`cloudflareAccountId` / `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`
(not `TYPESAFE_API_KEY`); do not set `TYPESAFE_BASE_URL` at the same time. The
client rewrites the body to `{ model: "typesafe/jev", input: { state, questions } }`
at `https://api.cloudflare.com/client/v4/accounts/{id}/ai/run`. `--model` does
not change that catalog id. `--cache` wraps Cloudflare inside the cache so keys
stay System One JSON. See the package README Providers section for model ids.

`check` and `generate` are offline. Live `run` and `eval` use provider
credentials; a format or rendering edit alone does not require a live call.

## Use factors for small Boolean derivations

Every factor is one predicate (`ref`) or one operator (`all`, `any`, `not`,
`at_least`). Use explicit `choice`, `noul`, `score` or supported `confidence`
predicates with finite `gt`, `gte`, `lt`, `lte` comparisons where needed.
Calibrate operational thresholds against the application's evaluation cases.

Keep these semantics in mind:

- A bare Noul in a Boolean operator means `noul >= 0.5`. It is not a calibrated
  authorization threshold. Choice and Score references require predicates.
- Missing answers normally throw. A `known`-only predicate is the exception
  for checking absent or unusable answers. `known` does not prove correctness.
- Boolean operators validate every operand, even when an earlier operand
  determines the result. Do not build a conditional decoder by assuming
  short-circuit behaviour or that `known` will guard a later missing operand.
- Weighted scores, required-versus-optional answers, calculations and workflow
  precedence belong in ordinary code. Factors do not authorize actions merely
  because their names contain words such as `safe` or `approved`.

## Organize domain files for humans

Prefer one file per coherent area and a separate `router.toml` when useful.
Keep local meanings and related authored material together. Split a file when
navigating it becomes harder than understanding the domain; one giant TOML is
not a goal.

The router owns distinctions between areas; domain files own their local
distinctions. These are organizational conventions, not built-in routing.
Application code imports and assembles files, handles ID collisions explicitly,
and decides scheduling. Separate files do not require separate model calls.
Independent questions can share a batch, but a question cannot consume another
answer from that same batch.

Use TOML when changing the definition is easier to review than changing code.
If an edit requires mentally executing conditions, loops or state transitions,
prefer a function. Do not invent include/merge rules or a workflow language to
make every part of an application fit in configuration.

## Author application data without imposing a universal schema

Apply these conventions to application-owned configuration and `[data]`. The
feature preserves and exports an arbitrary JSON-compatible tree beneath a
table root. Applications choose its structure, validation and interpretation.
Names such
as `topics`, `templates`, `utterances` or `examples` have no core semantics.

Choose content deliberately:

- Co-locate stable authored labels, descriptions, short copy, wording variants,
  domain metadata and representative cases that change together.
- Keep model instructions in questions. Application data is not automatically
  sent to the model; projecting selected values into a request requires code.
- Keep live facts, dynamic candidates and state in their authoritative runtime
  sources. Avoid duplicating prices, availability or capability lists across
  prompts and UI copy. A static authored policy may live in configuration when
  that configuration is its authoritative source.
- Keep rendering decisions, computations, consent, state changes and execution
  in code. A template can hold wording; it does not choose when to speak or
  supply facts. Literal braces do not imply a systemoneprompts template engine.
- Distinguish recognition examples, response utterances and evaluation cases.
  Held-out cases must not automatically become prompt examples. Example lists
  illustrate boundaries; they do not enumerate all supported wording.
- Keep secrets, private conversation histories and runtime logs out of authored
  definition files.

Format for easy scanning and review:

- Use shallow hierarchy and one header per meaningful collection, avoiding a
  repeated dotted header for each label or phrase.
- Prefer keyed tables for simple dictionaries. Prefer multiline arrays of
  compact inline records when entries have several fields, one record per row.
- Put each utterance on its own line in a variant list. Use multiline strings
  for paragraphs. Expand large records into tables or arrays of tables when a
  single row becomes unwieldy.
- Use stable IDs instead of list positions for references. Keep a predictable
  order, related entries together, and one authoritative definition per purpose.
- Use normal TOML values, not delimiter-separated strings or embedded expression
  languages. Comments should explain distinctions and ownership.
- Show a complete small domain when explaining a layout, focused diffs when
  reviewing an edit, and clearly label future or application-specific syntax.

The [delivery example](references/application-data.md)
illustrates compact records, multiline utterances and application-owned cases.
Its alternative keyed label table illustrates when records add needless noise.
These layouts are suggestions; follow an application's established schema.

Validate that schema in the application, preferably before runtime use. Check
duplicate record IDs, unknown fields, copy references, placeholders and code
registrations where relevant. Those are application guarantees, not core
systemoneprompts checks. A field such as `read_only = true` cannot enforce behaviour.
Inline examples also need an application adapter before they are CLI eval cases.

## Evaluate the decision, then report what was verified

The CLI eval format is JSONL: each case supplies `state`, optional `id`,
expected question `labels`, and/or expected Boolean `factors`. Choice labels
are option IDs, Noul labels are Booleans, and Score labels are integer indices.
Use full cases and defined factor names; inspect errors before provider calls.

Include contrastive, ambiguous and out-of-domain inputs. Keep held-out cases
separate from prompt examples. For a bad result, inspect the failed boundary
before adding more wording or changing a threshold. Application tests should
also verify any state or action invariants beyond classification.

Distinguish offline parsing, generation and supplied-answer checks from live
recognition evaluation. Report the checks actually run. Keep the change scoped
to package usage unless the user also requests library implementation work.
