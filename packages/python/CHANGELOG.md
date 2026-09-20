# Changelog

## 0.1.0 (unreleased)

Complete Python implementation of the v1 contract, with TypeScript as the
behavior reference.

- Renamed the Python package from `jevprompts` to `systemoneprompts` (PyPI
  name, import, CLI, `python -m`, live extra, cache directory, User-Agent).
  `JevError` is now `SystemOnePromptsError`; the live HTTP client is
  `TypeSafeClient` (`TypeSafeClientError`, `TypeSafeHttpError`).
- Parse TOML definitions into native TypeSafe question dictionaries with
  structured diagnostics, source locations, requirement conflicts, factor
  primitive checks, cycles, and backtick warnings.
- Evaluate factors without network access, preserving missing-answer errors and
  the fixed bare-Noul cutoff.
- Generate deterministic `<stem>_generated.py` modules with TypedDict/Literal
  annotations, required state/answer fields, atomic writes, and stable source
  hashes. `assert_state` returns `None` and does not provide TypeScript-style
  narrowing.
- Provide `check`, `generate`, offline `run --answers`, live `run`/`eval`, and
  `cache stats|clear` CLI commands. Usage failures exit 1.
- Cache System One requests per question through a fetch/httpx2 transport hook.
  Cache misses forward through urllib by default, or through `httpx2.HTTPTransport`
  when a live client is constructed with `--cache`. Canonical JSON matches
  JavaScript `JSON.stringify` after recursive key sort, including integer-index
  key order, IEEE-754 numbers, and unpaired surrogates. Eval Noul labels use
  JavaScript `String` spellings (`true`/`false`). External JSON parsing follows
  `JSON.parse` (no `NaN` / `Infinity` tokens).
- Evaluate JSONL cases with confusion tables, JS-compatible rounding, first
  numeric-field sweeps, partial reports, and report overwrite protection.
- `run_many` accepts shared `questions`+`states` or per-item `{state, questions}`
  mappings (mutually exclusive). It preserves input order and collects per-item
  errors. `walk_taxonomy` performs native Choice beam search.
- Optional extra `systemoneprompts[live]` installs `pydantic>=2.13,<3` and
  `httpx2>=2.13,<3`. `TypeSafeClient` talks to TypeSafe System One over HTTP
  (`system_one` and sync `system_one_sync`). 429s are `TypeSafeRateLimitError`
  with numeric or HTTP-date `Retry-After`. Deterministic checks never read
  `TYPESAFE_API_KEY`.
- Answer helpers (`wire_questions`, `noul_value` / `choice_label` /
  `score_value`, `partition_answers`) live on the core import path. Read-only
  cache misses raise `CacheMissError`. `[requires]` `[]` means every array
  element; empty arrays satisfy it.
- Reference parity details: parsed TOML tables enumerate integer-like keys
  first in numeric order like JavaScript objects; diagnostic messages render
  values with JavaScript `String()` spellings; typo hints measure UTF-16 code
  units; line numbers split only on `\n` / `\r\n`; files are read without
  newline translation and invalid UTF-8 decodes to U+FFFD; every factor cycle
  back edge is reported; `run --json` and eval reports omit `cache` when no
  cache is active, spell integer-valued numbers as `1`, order keys like
  JavaScript objects, and emit non-ASCII literally.
- Cache misses drop a stale `Content-Length` header before forwarding the
  rewritten body (previously every cold `--cache` request failed). `cache=True`
  wraps a caller-supplied `transport`; a caller `http_client` cannot be cached.
- Cache records, forwarded miss bodies, and CLI JSON are written with a
  `JSON.stringify`-exact serializer (`json_values.js_json_dumps`): TypeScript
  field order (`hash`, `requestedModel`, `reportedModel`, `answer`), JavaScript
  number spellings, literal non-ASCII, and escaped lone surrogates, so cache
  directories written by either package are byte-identical. A request without a
  `state` key hashes like TypeScript (distinct from `state: null`). Only ASCII
  digits count as integer-like keys (`str.isdigit()` also accepted `²`/`٣`).
  Integer literals beyond IEEE-754 range parse to `inf` and serialize as `null`
  like `JSON.parse`/`JSON.stringify` instead of raising. Corrupt cache files
  (invalid UTF-8, extreme nesting, `NaN` tokens, non-finite numbers) are misses.
- TOML integers outside JavaScript's safe range (`|n| > 2**53 - 1`) are a
  `toml-syntax` error located at the literal, as `smol-toml` rejects them
  ("integer value cannot be represented losslessly"). `walk_taxonomy` treats
  probabilities beyond float range as infinite rather than raising.
- Generated modules handle Python keywords as ids, annotate empty tables for
  `mypy --strict`, and keep answer aliases unique when ids clean to the same name.
- Factor predicates treat `choice = ""` as a real check, reject explicit `null`
  comparators like the reference, and report huge integers as non-finite.
- State assertions say `got undefined` for missing values (TypeScript wording)
  and traverse any mapping; non-string requirement keys raise
  `invalid-require-path`.
- `run_many` accepts sync clients and `concurrency=None`, returns `None` results
  as-is, and lets `BaseException` propagate. `walk_taxonomy` raises `TypeError`
  when a response lacks `step` probabilities. `TaxonomyNode` is exported.
- Release tooling: `package-smoke.py` installs into the running interpreter's
  version; `release-prepare.py` accepts final versions only; wheel metadata
  carries Trove classifiers; the sdist excludes repository-only files.
