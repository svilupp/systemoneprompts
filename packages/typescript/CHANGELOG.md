# Changelog

## 0.1.0 (unreleased)

Initial release. Package renamed from `jevprompts` to `systemoneprompts`.

Correctness hardening:

- Reject empty question sets, non-JSON descriptions, incompatible requirements, and misplaced factor fields.
- Support nested indexed state paths and preserve literal IDs such as `__proto__` through parsing, generation, and evaluation.
- Report independent factor cycles and reject missing answers even in short-circuited Boolean expressions.
- Validate cache records and live answers before reuse; write entries atomically and retain HTTP response metadata.
- Validate eval inputs before requests, report case failures through the exit status, and protect generation from output collisions.
- Validate batch/beam limits and invoke result callbacks once.

Initial feature set:

- Parse TOML decision definitions into native TypeSafe question objects; structural problems are collected in `definition.diagnostics`
- `[requires]` path/type guarantees including `[]` (every array element), `createStateAssert`, prefix-conflict check, and backtick lint with nearest-match hints
- Boolean `[factors]` with operators, predicates (`known` / `choice` / `noul` / `score` / `confidence`), toposort, primitive-aware validation, and a pure evaluator typed by native System One answers
- Deterministic `*.generated.ts` emission; `RequiredState` is a valid `EntryType`; `model` exported as `string | undefined`
- `TypeSafeClient` talks to TypeSafe System One over `fetch` (`TYPESAFE_API_KEY`, injectable `fetch` / `timeout`); 429s are `TypeSafeRateLimitError` with HTTP-date `Retry-After`; no `@typesafe-ai/sdk` dependency
- Answer helpers: `wireQuestions`, `noulValue` / `choiceLabel` / `scoreValue`, `partitionAnswers` (no Score level field)
- CLI: `check`, `generate [--check]`, `run [--cache] [--json] [--model]`, `eval [--sweep] [--report]`, `cache stats|clear`
- `systemoneprompts/dev`: per-question caching `fetch` with cumulative stats; read-only misses are `CacheMissError`; error responses pass through untouched
- `systemoneprompts/patterns`: `runMany` (shared `questions`+`states`, or per-item `{state, questions}`), `walkTaxonomy`
