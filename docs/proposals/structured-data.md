# Proposal: application-owned structured data

Status: implemented, 20 September 2026. This document records the structured
`[data]` contract in the [definition specification](../SPEC.md) and its
application-authoring guidance.

## Decision

Add one optional top-level `data` table to a systemoneprompts definition. Preserve
its arbitrary JSON-compatible structure in `definition.data` and export it as
`data` in generated TypeScript and Python modules.

Applications decide what belongs inside it, how to validate it, and how to
consume it. systemoneprompts assigns no meaning to its keys or strings.

That is the entire feature. Domain catalogues, response templates, utterance
variants, UI labels and small example sets are possible uses, not new built-in
systemoneprompts concepts. Authoring guidance below recommends useful conventions
without requiring them.

## Motivation and boundary

Today, definitions preserve extra scalar metadata, but unknown top-level
tables produce warnings and are omitted from the parsed definition. Structured
question instructions and criteria are already supported, but those values
belong to the provider request. They are the wrong home for application-only
copy and metadata.

A dedicated namespace lets humans keep related authored material together:
the meanings an application recognizes, the wording it presents, and a few
examples that explain the distinctions. Applications retain ordinary code for
runtime facts, dynamic candidates, state transitions and execution.

The feature is useful beyond conversation: classification labels and reviewer
guidance, document categories and display names, moderation explanations, or
intake choices and help text can share the same pattern.

Success means fewer independent representations to coordinate during an edit.
Moving code into TOML without improving that experience is not a goal.

## Proposed core contract

### Shape and values

- `data` is optional. When absent, the parsed definition and generated module
  expose an empty object/dictionary.
- When present, its root must be a TOML table, including an equivalent inline
  table. Arrays and scalar values at the root are structural errors.
- Below that root, arbitrary nested objects, arrays, strings, booleans and
  finite JSON-compatible numbers are allowed. Nested array-of-table syntax is
  also ordinary TOML and is supported.
- Apply the existing JSON-value rules used for question payloads. Reject TOML
  date/time values and non-finite numbers; quote dates to represent strings.
  TOML has no null literal, and this proposal introduces no null encoding.
- There are no reserved child keys, required record fields, prescribed IDs,
  nesting conventions, or application-schema versions.
- Preserve parsed values, literal keys and array order. Do not normalize IDs,
  interpolate strings, flatten structures, insert application defaults or
  resolve references. Object key order is not an application semantic contract.
- Preservation concerns parsed data, not TOML comments or source formatting.
  Multiline strings retain their values according to normal TOML parsing.

The root table provides a namespace; “arbitrary structure” applies within it.
It does not mean arbitrary executable values or a new serialization language.

### Parsing and diagnostics

Recognize `data` alongside `requires`, `questions` and `factors`, and expose it
separately from `meta`. Keep existing scalar metadata behaviour for other keys.
Unknown top-level tables outside `data` continue to warn, preserving typo
detection for the actual definition language.

Follow existing error handling: invalid TOML throws; structural errors become
diagnostics. Proposed diagnostic codes are `data-type` for a non-table root and
`data-json` for a non-JSON-compatible descendant. Locate the offending path as
precisely as the source index permits. For an invalid data tree, return an empty
`data` object with errors rather than a partially usable tree; normal generation
and execution checks must reject those errors.

Inside `data`, arbitrary keys are intentional. Core checking does not validate
record IDs, application references, placeholders, filenames or backticked
paths. Duplicate TOML keys remain syntax errors, but two records with the same
application-defined `id` are an application validation concern.

### Generation and consumption

Both language packages export `data` alongside their existing exports. Keep
generation deterministic and preserve values across parsing and generation,
including empty containers, multiline text, Unicode and unusual literal keys.
Use the existing safe emission rules for keys such as `__proto__`.

TypeScript can expose the generated literal using `as const`; Python can
expose an ordinary dictionary. Neither requires generation of an application
schema. Static TypeScript readonly inference is not a promise of runtime deep
freezing. The application validates or adapts the result into its own types.

Illustrative consumption, after this feature is implemented:

```ts
import { data, questions } from "./delivery.generated.js";

const delivery = validateDeliveryData(data); // Application-owned function.
// The application uses delivery for labels, copy, or other authored content.
// questions remains the existing native TypeSafe question object.
```

No new core schema registry, callback mechanism or plugin API is necessary.

### No implicit runtime effects

- Do not send `data` to a provider or merge it into state or questions.
- Do not interpret strings as handlers, imports, expressions or templates.
- Do not make factors able to reference `data` through new syntax.
- Do not load referenced files, discover domains, merge definitions or route
  requests based on `data`.
- Do not automatically render copy or convert inline examples into eval cases.
- Do not apply question backtick linting to application strings.

Application code can explicitly project selected data into native questions or
state. Once it does, those values are part of the actual provider request and
follow normal validation, payload and cache behaviour.

Editing application-only copy changes the generated source, including its
source hash, but must not change a provider request or its request-based cache
key unless the application explicitly uses that copy in the request.

## Suggested file organization

Organize files around areas humans maintain together:

```text
definitions/
  router.toml
  delivery.toml
  catalogue.toml
  conversation.toml
```

The router owns distinctions between domains. A domain file owns its local
questions and related application data. These filenames and responsibilities
are conventions, not special loader behaviour.

Application code imports and assembles definitions explicitly. If combining
question dictionaries, it must handle names and collisions deliberately rather
than silently overwriting duplicate IDs. Separate files do not imply separate
model calls: independent questions can still be assembled into one batch.
Conversely, consuming a router answer to choose a later request is an explicit
application scheduling decision.

The existing requirement for at least one question remains unchanged. This
proposal does not make systemoneprompts a loader for data-only TOML files; an
application may load those with its normal TOML parser.

## Example: one delivery domain

This is valid TOML illustrating the feature. Only `data` is a new
core field. Every name beneath it is chosen by this example application.

```toml
title = "Delivery"
description = "Delivery prices and timing."

[requires]
"message" = "string"

[questions.topic]
type = "choice"
instructions = """
Identify the delivery information being requested.
Asking about a delivery method does not select it.
"""

[questions.topic.criteria]
cost = "Asks about delivery prices or charges."
timing = "Asks when delivery arrives or how long it takes."
none = "No delivery-information request."
unclear = "A delivery question whose meaning is uncertain."

[data]

# Compact records: one entry per row.
topics = [
  { id = "cost",   label = "Delivery prices", scope = "delivery_method", reply = "cost" },
  { id = "timing", label = "Delivery times",  scope = "delivery_method", reply = "timing" },
]

templates = [
  { id = "cost",          text = "{method_label} costs {price_label}." },
  { id = "timing",        text = "{method_label}: {timing_label}." },
  { id = "missing_scope", text = "Which delivery method do you mean?" },
  { id = "unavailable",   text = "I don’t have that delivery information." },
]

# Expand lists when each utterance deserves its own line.
utterances = [
  { id = "acknowledge", variants = [
    "Of course.",
    "Sure.",
    "Happy to help.",
  ] },
  { id = "explain", variants = [
    """
I can explain delivery prices and timing.
The available options depend on your order.
""",
  ] },
]

# Application-owned recognition checks, not prompt examples.
examples = [
  { message = "what would express set me back?", labels = { topic = "cost" } },
  { message = "how long does standard take?",    labels = { topic = "timing" } },
  { message = "use express",                    labels = { topic = "none" } },
]
```

The application supplies current delivery methods and verified price/timing
values. It validates topic IDs, reply references and placeholders, and decides
whether any acknowledgement or clarification is appropriate. Core systemoneprompts
does none of those things. Literal braces in a string have no built-in meaning.

The `examples` records are not directly the existing CLI eval format: an
application adapter must construct the complete state and expected labels.
They are convenient local checks; larger held-out datasets belong elsewhere.

## Authoring principles for humans and agents

These are advisory principles suitable for a future authoring skill or
playbook. They are not parser rules, and they do not prescribe a universal
application schema. Follow an application's existing conventions first.

### Choose what belongs in the file

1. Co-locate human-authored material that usually changes together: semantic
   distinctions, display labels, short copy, wording variants, domain metadata
   and representative examples.
2. Keep provider-facing descriptions in questions. Put application-only
   material under `data`. Do not move a needed model instruction into `data`
   and assume the model will still see it.
3. Keep authoritative runtime facts in their sources. Code should supply live
   prices, stock, permissions, available actions and current state. A static
   authored policy may belong in configuration when that is its authoritative
   source; avoid maintaining a second contradictory copy.
4. Keep calculations, consent, state transitions, persistence, retries,
   conditional decoding and action execution in code. If editing a record
   requires mentally executing branches or loops, consider a function instead.
5. Do not use versioned authored data as a place for credentials, private
   conversation records or runtime logs.
6. Distinguish model examples, authored responses and evaluation utterances.
   Never automatically turn held-out tests into prompt examples or grow sample
   wording into an exhaustive phrase-matching system.

### Structure and display for review

1. Prefer one file per coherent domain or area, with a separate router where
   useful. Split further when files become difficult to navigate; avoid a
   single application-wide catalogue merely to claim everything is co-located.
2. Use a shallow hierarchy and a header per meaningful collection, not a
   header per label or phrase. Avoid repeating long dotted paths for each item.
3. Use keyed tables for simple dictionaries; use arrays of inline records when
   entries have several fields. Within a multiline array, put one short record
   on each row. Put one utterance per line in variant lists.
4. Expand complex records using normal TOML tables or arrays of tables when a
   single row becomes hard to read. Compactness is a preference, not a maximum
   line-length contest. Use multiline strings for paragraphs.
5. Use stable, descriptive IDs for application references. Avoid references by
   list position. Keep a predictable order and group related entries together.
6. Keep one authoritative description for each purpose. Do not duplicate the
   same meaning across prompts, catalogues and help lists without a reason;
   derive repeated views in explicit application code when useful.
7. Do not introduce delimiters inside strings to simulate records or invent a
   second expression language. Use normal TOML values.
8. Use comments to explain distinctions and ownership, not to repeat fields.
   Show complete domain examples when explaining a layout, and show focused
   diffs when reviewing an edit. Label future or application-specific syntax
   clearly.

For a simple dictionary, this may be clearer than repeating `id` and `text`:

```toml
[data.labels]
cost = "Delivery prices"
timing = "Delivery times"
```

This is an alternative layout, not a required companion to `topics`. A header
for the collection is useful; a separate `[data.labels.cost]` table for a single
string usually is not.

### Validate the application's conventions

Core validation only establishes that `data` is a portable tree. Applications
should validate the structure they actually consume before using it, preferably
at startup or build time with their existing type/schema tools.

Depending on the application, useful checks include duplicate record IDs,
unknown fields, broken copy references, expected template placeholders,
supported scope names and correspondence with explicit code registrations.
Do not describe these checks as systemoneprompts guarantees. Adding a `read_only`
field, for example, declares intent but cannot enforce side-effect behaviour.

If application conventions need independent versioning, the application may
put a schema version inside `data`. systemoneprompts neither requires nor interprets
that value.

## Scope exclusions

This proposal adds no rendering engine, schema language, automatic catalogue
projection, domain loader, include/merge mechanism, dynamic question builder,
routing scheduler, handler binding, workflow language, new CLI command, or
automatic eval conversion. It does not install or create an authoring skill.

Those would be separate proposals, justified by repeated downstream needs.
Small application functions are the default bridge between authored data and
runtime behaviour.

## Implementation and compatibility plan

Implementation completed:

1. Updated the shared specification with the optional table, value constraints,
   diagnostics, non-forwarding boundary and generated export.
2. Added shared conformance coverage and implemented parsing/checking and generation
   in both language packages. Keep idiomatic APIs and identical data values.
3. Updated public definition types and construction sites. Accounted for consumers
   that construct definitions directly, including Python dataclass callers;
   avoid unnecessarily breaking constructor argument positions.
4. Added package examples/tests and documented application-owned validation.
   Regenerate affected checked-in output and synchronize shipped references
   through the existing repository tooling.
5. Ran the affected deterministic package checks and shared conformance checks.
   No live model evaluation is needed to establish preservation and isolation.

This is additive for definitions that do not use the key `data`, but reserving
that name needs a compatibility note. An existing scalar `data = "..."` would
stop being generic scalar metadata and become an error; an existing ignored
`[data]` table would become preserved data. Assess contract/package versioning
under the repository's compatibility policy rather than calling the change
unconditionally backwards compatible. Unrelated warnings retain their meaning.

Acceptance checks should establish:

- Missing and empty data expose `{}` consistently in both packages.
- Deep nesting, mixed arrays, nested arrays of tables, arbitrary keys and
  multiline strings survive parsing and generated-module consumption.
- Invalid root types, dates/times and non-finite numbers produce useful errors
  before generation or provider execution.
- Question-like keys and backticks inside data remain inert. The same typos
  outside data still receive existing definition diagnostics.
- Application-specific record fields, duplicate record IDs and strings that
  resemble references are preserved without interpretation.
- Provider requests and request-based cache identities are unchanged by edits
  confined to unused data; explicit application projections behave normally.
- Generation stays deterministic and safe for unusual object keys; generated
  modules work in clean TypeScript and Python consumers.
- Existing question, requirement and factor semantics remain unchanged.

The proposal is complete when the core remains a small preservation/export
feature and the guidance helps applications keep their own conventions legible.
