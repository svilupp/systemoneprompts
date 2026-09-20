# systemoneprompts definition contract

Status: contract version `v1`. The TypeScript package is the reference
implementation; the Python package is required to match the language-neutral
rules below. Package-specific APIs may be idiomatic, but the parsed questions,
state guarantees, factor truth tables, diagnostics, and generated artifacts
must preserve the same behavior.

## Definition shape

A definition is a TOML document with optional scalar metadata (`title`,
`version`, `description`, `model`, plus other scalar keys) and four recognized
tables: `[requires]`, `[questions]`, `[factors]`, and optional `[data]`. Unknown top-level tables
produce warnings and are not silently interpreted. `model` is an optional
non-empty string; a blank model is an error.

The parser throws only for invalid TOML. Structural problems are returned as
diagnostics and the invalid entry is omitted. `checkDefinition`/`check_definition`
adds cross-cutting reference, conflict, cycle, and lint diagnostics.

## Application data

`[data]` is an optional application-owned namespace. Its root must be a TOML
table. Beneath it, arbitrary nested JSON-compatible objects, arrays, strings,
booleans, finite numbers, and arrays of tables are preserved verbatim. TOML
dates/times and other non-JSON values are rejected with diagnostics. An absent
or invalid data tree is represented as an empty object/dictionary when the
definition is returned; invalid definitions still fail normal checking and
generation.

systemoneprompts does not assign meaning to child keys, validate application IDs or
placeholders, resolve references, interpolate strings, load files, send data
to TypeSafe, or make factors and questions depend on it. It does not apply
question backtick linting inside data. Applications decide their own schema,
validation and runtime use. Generated TypeScript and Python modules export the
parsed tree as `data`; generated output remains deterministic. Application-only
data therefore has no provider or cache effect unless application code
explicitly projects it into a question or state.

## Questions

At least one question is required. Question IDs are literal TOML keys, including
quoted IDs containing dots. Every question is a table with only `type`,
`instructions`, and `criteria`:

- `noul`: optional `criteria` table with only `true` and `false` entries.
- `choice`: non-empty criteria table with at most 255 labels.
- `score`: criteria array with at least two entries.

`instructions` and criteria entries are forwarded verbatim when they are a
string, JSON-compatible table, or JSON-compatible array. TOML dates, times,
cycles, non-finite numbers, and other runtime-only values are rejected. The
resulting objects use the native TypeSafe field names and shapes; no aliases or
implicit question vocabulary are introduced.

Native System One answers under a response `answers` map:

- Noul: type `noul` and a finite `noul` number.
- Choice: type `choice`, a `choice` label, finite `confidence`, and `probabilities` with a finite probability for every criteria label.
- Score: type `score`, a finite `score` expected value (a float between levels, not a level label), finite `confidence`, plus `legend` and `probabilities` keyed by the decimal string of each criteria index (`"0"`, `"1"`, ...).

Packages may expose helpers that read those fields and that partition answers into valid, missing, and malformed ids. They must not invent a Score level as a native field. `wireQuestions` / `wire_questions` returns only `type`, `instructions`, and `criteria` for each question.

## State requirements

`[requires]` maps dotted and indexed paths to one of:
`string`, `number`, `boolean`, `array`, `object`, `null`, or `exists`.
Paths use own object keys, zero-based `[n]` indexes, and empty `[]` indexes.
`[]` means every array element: `"messages[].text" = "string"` requires
`messages` to be an array and every element's `text` to be a string. An empty
array satisfies a `[]` requirement; a container that is not an array fails as
`messages: expected array, got <type>`. `[]` and `[n]` both imply an array
container and do not conflict with each other. A backticked `[n]` path is
guaranteed when `[requires]` names the same path with `[]`; a backticked `[]`
path is not guaranteed by a more specific `[n]` requirement. `exists` accepts
null; all other types require the value to match. `number`, `array`, and
`object` also require JSON-compatible values. Assertions never copy, coerce, or
reshape the application state.

Explicit requirements and containers implied by descendants must agree. For
example, `ticket = "object"` may accompany `ticket.message`, while
`ticket = "string"` may not. Dotted and indexed descendants cannot require the
same container to be both an object and an array. Equivalent index spellings
refer to the same index, and out-of-bounds indexes fail at runtime.

## Factors

Every factor evaluates to a Boolean. A factor is exactly one predicate (`ref`)
or one Boolean operator (`all`, `any`, `not`, `at_least`). Predicate fields are
`known`, `choice`, `noul`, `score`, and `confidence`; numeric fields use one or
more finite comparators from `gt`, `gte`, `lt`, and `lte` and all present
comparators are ANDed.

Bare Noul references in Boolean operators use `noul >= 0.5`. Choice and Score
answers must be wrapped in a predicate. Missing answers are runtime errors, not
false values, except a `known`-only predicate: it returns false for an absent
or unusable answer. `known` treats explicit `missing`, confidence `0`, and a
bare Noul exactly equal to `0.5` as unknown; usable Choice and Score answers
are known.

Boolean operators validate every operand even if an earlier operand already
determines the result. Factor definitions are snapshotted when an evaluator is
created, factor IDs are prototype-safe, and independent cycles are reported
together. Unknown references, question/factor ID collisions, invalid operator
fields, invalid choice labels, primitive mismatches, and cycles are definition
errors.

## Generation and CLI

Generation is deterministic. It emits native question objects, model metadata,
the verbatim factor definitions, a state assertion, and a typed factor
evaluator. Empty requirements still produce a state type assignable to the
package `EntryType`. Generated output must typecheck/import in a clean
consumer.

The CLI supports `check`, `generate`, `run`, `eval`, and `cache`. `check` and
`generate --check` process every input and return nonzero if any input fails.
They never call the provider. `run` validates state before any request. `eval`
validates cases, labels, factor names, sweep fields, and report paths before
requests; partial reports survive execution errors. Live credentials are
required only by explicit live commands.

## Cache and patterns

The TypeScript development cache is a fetch interceptor, not a client wrapper.
It keys per-question requests by canonical JSON request data and model, writes
records atomically, treats malformed records as misses, validates cached
answers against the question criteria, and merges valid cached hits with valid
live answers. Read-only misses fail. Cache statistics are cumulative and
prototype-safe.

`runMany` requires a positive concurrency limit, preserves input order, and
invokes a result callback at most once per result. It may ask the same
questions about many states, or a list of `{state, questions}` items. Callback
failures reject the batch without retries. `walkTaxonomy` requires a positive
beam width and is an explicit approximate beam search; it does not promise an
exhaustive traversal.

## Compatibility

The TOML author-owned `version` is distinct from this behavioral contract
version. Cases in `conformance/v1` are the executable compatibility boundary.
Any change to native question shape, state assertion semantics, factor truth
tables, diagnostic codes, cache records, or CLI exit behavior requires a new
fixture and a compatibility review.
