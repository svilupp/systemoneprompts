# systemoneprompts Python

The Python implementation of the language-neutral systemoneprompts definition
format. It is self-contained under `packages/python/` and is intentionally
offline-first: parsing, diagnostics, state contracts, factor evaluation,
generation, cache helpers, evaluation metrics, and orchestration helpers do
not require provider credentials.

TypeScript remains the reference implementation. Both packages share the
checked-in v1 corpus under `../../conformance/v1`.

## Install and check

```bash
uv sync --locked --dev
uv run --locked python scripts/check.py
uv run --locked python scripts/package-smoke.py
```

The package-local check runner executes lint, unit tests, mypy, wheel build,
and conformance as independent legs. `scripts/run-quiet.sh` keeps normal CI
output short while preserving the complete failing log.

Live TypeSafe calls are optional:

```bash
uv sync --locked --dev --extra live
uv run --locked --extra live pytest live
```

```python
from systemoneprompts.client import TypeSafeClient

client = TypeSafeClient()  # TYPESAFE_API_KEY
# or TypeSafeClient(http_client=httpx2.Client(timeout=60))
result = await client.system_one(state=state, questions=questions)
```

## CLI

```bash
uv run systemoneprompts check definition.toml
uv run systemoneprompts generate definition.toml --out build/
uv run systemoneprompts generate definition.toml --check --out build/definition_generated.py
uv run systemoneprompts run definition.toml --state state.json --answers answers.json
uv run systemoneprompts run definition.toml --state state.json --json --model jev-latest
uv run systemoneprompts eval definition.toml --cases cases.jsonl --report report.json
uv run systemoneprompts cache stats
uv run systemoneprompts cache clear
# state can also be read from stdin with --state - or by omitting --state
```

`run --answers` is an explicit offline workflow: it asserts state, evaluates
supplied answers, and never constructs a TypeSafe client. Live `run`/`eval`
require `systemoneprompts[live]` and `TYPESAFE_API_KEY`.

Generated modules are named `<stem>_generated.py` (TypeScript uses
`<stem>.generated.ts`). They export `meta`, `data`, `model`, `requires`,
`RequiredState`, `assert_state`, `questions`, `Answers`, `factor_definitions`,
`Factors`, and `evaluate_factors`. `assert_state` returns `None` and does not
narrow types.

The optional `[data]` table is preserved as application-owned structured data
and is exported from generated modules as `data`. Its contents must be a
JSON-compatible TOML tree, but systemoneprompts assigns no meaning to keys, records,
templates or references inside it. Applications should validate the shape they
consume and keep runtime facts, state transitions and execution in code.

## Public modules

- `systemoneprompts.definition`: TOML parsing and cross-cutting validation.
- `systemoneprompts.answers`: answer shape checks, `wire_questions`, and noul/choice/score accessors.
- `systemoneprompts.requirements`: dotted, indexed, and `[]` state paths and assertions.
- `systemoneprompts.factors`: Boolean factor compilation and pure evaluation.
- `systemoneprompts.generator`: deterministic importable module generation.
- `systemoneprompts.model`: provider-neutral model precedence helpers.
- `systemoneprompts.patterns`: async `run_many` (shared questions+states or per-item `{state, questions}`) and native Choice taxonomy walking.
- `systemoneprompts.cache`: optional per-question System One cache (not imported by the core).
  Misses forward through urllib, or through `httpx2.HTTPTransport` when a live client is constructed with `--cache`.
- `systemoneprompts.evaluation`: eval-case metrics, sweeps, and reports.
- `systemoneprompts.client`: native TypeSafe System One HTTP client (`pydantic` + `httpx2`) behind `systemoneprompts[live]`. Pass `http_client` or `transport` for custom timeouts and tests. `system_one_sync` is the blocking counterpart.
- `systemoneprompts.provider`: CLI `create_client`, `FakeClient`, and cache transport wrapping.

See the systemoneprompts repository `docs/SPEC.html` and `docs/compatibility.md`
for the language-neutral contract. Shared corpus copies live under
`conformance/v1` so this package remains usable when copied out of the
repository.
