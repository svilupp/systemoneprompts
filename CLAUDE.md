# Repository guide

Read [`README.md`](README.md), [`docs/SPEC.md`](docs/SPEC.md), and
[`docs/releasing.md`](docs/releasing.md) before changing behavior.

The two packages are independent. TypeScript is the reference implementation;
Python follows the same contract through [`conformance/v1`](conformance/v1/).
Keep the shared corpus and both package copies in sync with
`tools/sync-shared.py`.

Useful code paths:

- Parsing and diagnostics: `packages/typescript/src/definition/` and
  `packages/python/src/systemoneprompts/definition.py` plus `diagnostics.py`.
- State requirements: `packages/typescript/src/state/` and
  `packages/python/src/systemoneprompts/requirements.py`.
- Factors: `packages/typescript/src/factors/` and
  `packages/python/src/systemoneprompts/factors.py`.
- Generated output: `packages/typescript/src/generate/` and
  `packages/python/src/systemoneprompts/generator.py`.
- CLI dispatch: `packages/typescript/src/cli/` and
  `packages/python/src/systemoneprompts/cli.py`.
- Fixtures and contract tests: `packages/*/tests/` and `conformance/v1/`.

Use the package quiet checks by default. They run each leg through the local
`scripts/run-quiet.sh` and retain full logs for failures:

```sh
cd packages/typescript && sh scripts/run-quiet.sh "Checks" -- bun run check
cd packages/python && sh scripts/run-quiet.sh "Checks" -- uv run --locked python scripts/check.py
```

Use the same wrapper for package smoke, release, and focused test commands.
Deterministic checks stay offline; live provider tests are explicit and require
`TYPESAFE_API_KEY`.
