# systemoneprompts Python

Define TypeSafe questions, required state, and Boolean factors in TOML.
Generate typed Python modules and call the System One API.

## Quick start

Requires Python 3.11+. The core package has no dependencies; API calls need
the `live` extra and `TYPESAFE_API_KEY`.

```sh
pip install 'systemoneprompts[live]'
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
systemoneprompts generate triage.toml
```

```python
from systemoneprompts.client import TypeSafeClient
from triage_generated import assert_state, evaluate_factors, model, questions

state = {"ticket": {"message": "I was charged twice."}}
assert_state(state)
client = TypeSafeClient()
try:
    response = client.system_one_sync(state=state, questions=questions, model=model)
    print(evaluate_factors(response["answers"])["billing"])
finally:
    client.close()
```

Async code can use `await client.system_one(...)`.
`assert_state` validates the original state and returns `None`.

## Definitions and API

Both packages share the [definition format](docs/SPEC.html).
`[requires]` validates state paths, `[questions]` holds TypeSafe question
objects, and `[factors]` computes Boolean results from answers.
Optional `[data]` holds JSON-compatible application data, exported without
sending it to the provider.

Import core functions from `systemoneprompts`:

| Function | Purpose |
| --- | --- |
| `parse_definition(toml)` / `load_definition(path)` | Read a definition |
| `check_definition(definition)` | Collect validation errors and warnings |
| `create_state_assert(definition.requires)` | Validate state |
| `create_factor_evaluator(definition.factor_definitions)` | Compute Boolean factors from answers |
| `generate(definition, output)` | Write a Python module |
| `run_many` / `walk_taxonomy` | Run batches or search Choice trees |

Invalid TOML throws `SystemOnePromptsError`. Definition errors are returned as
diagnostics; generation rejects definitions with errors.

Generated `<stem>_generated.py` modules export questions, model, metadata,
application data, state assertions, and factor evaluators, with types for
state, answers, and factors. See the [examples](examples/) for patterns.

## CLI

```sh
systemoneprompts check triage.toml --strict
systemoneprompts generate triage.toml --check
systemoneprompts run triage.toml --state state.json --answers answers.json
systemoneprompts run triage.toml --state state.json --cache --json
systemoneprompts eval triage.toml --cases cases.jsonl --report report.json
systemoneprompts cache stats
```

`generate --check` fails if generated files are stale.
`run --answers` evaluates saved answers without an API call.
State can come from stdin with `--state -` or by omitting `--state`.
`--cache` reuses per-question answers from `.systemoneprompts/cache`.

Each eval case has `state` and optional `id`, `labels`, and `factors`.
Labels are Choice strings, Noul Booleans, or integer Score levels.
`--sweep <factor>` compares thresholds.

CLI model precedence: `--model`, TOML `model`, `TYPESAFE_MODEL`,
`TYPESAFE_DEFAULT_MODEL`, then `jev-latest`.

## Development

Run from this package directory:

```sh
uv sync --locked --dev
sh scripts/run-quiet.sh "Checks" -- uv run --locked python scripts/check.py
sh scripts/run-quiet.sh "Release checks" -- uv run --locked python scripts/release-check.py
```

Checks cover lint, tests, types, builds, shared test cases, and generated
examples. Release checks also test wheel and sdist installs and a copy of the
package outside the repository. Use `scripts/run-quiet.sh` for focused tests
too; it retains full logs and prints failures.

After editing example definitions, run
`uv run --locked systemoneprompts generate examples/*/*.toml`.

Live tests require `TYPESAFE_API_KEY`:

```sh
uv sync --locked --dev --extra live
sh scripts/run-quiet.sh "Live tests" -- uv run --locked --extra live pytest live
```

After release checks pass, `uv run --locked python scripts/publish.py` builds
and publishes the wheel and sdist to PyPI.
