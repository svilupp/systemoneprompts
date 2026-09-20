# Python package guide

Read [`README.md`](README.md) for the API and CLI. This package is portable
when copied outside the repository and follows the shared v1 corpus.

Code map:

- `src/systemoneprompts/definition.py`, `diagnostics.py`: parsing and checks.
- `requirements.py`, `factors.py`: state paths and Boolean evaluation.
- `generator.py`: deterministic module output.
- `cli.py`, `provider.py`: command dispatch and provider setup.
- `tests/fixtures/` and `tests/test_conformance.py`: contract coverage.
- `scripts/conformance.py`: adapter checks against `conformance/v1`.

Keep the core dependency-free, preserve native TypeSafe shapes and stable
diagnostic codes, and keep live transport in the optional `live` extra.

Default agent checks:

```sh
./scripts/run-quiet.sh "Checks" -- uv run --locked python scripts/check.py
./scripts/run-quiet.sh "Package smoke" -- uv run --locked python scripts/package-smoke.py
```

Use raw `pytest` or a named check leg only for focused debugging. Deterministic
checks never contact TypeSafe.
