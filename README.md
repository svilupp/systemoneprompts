# systemoneprompts

TOML decision definitions for System One. The TypeScript and Python packages
share the format and the v1 conformance cases.

Definitions contain native TypeSafe questions, required state paths, and
Boolean factors. The packages validate them before a provider call and expose
the results through native language APIs. TypeSafe and JEV are providers, not
the product name.

## Packages

| Package | Install | Default check |
| --- | --- | --- |
| [`packages/typescript`](packages/typescript/) | `bun install --frozen-lockfile` | `bun run check` |
| [`packages/python`](packages/python/) | `uv sync --locked --dev` | `uv run --locked python scripts/check.py` |

Run commands from the package directory. The package check runners use
`scripts/run-quiet.sh`: successful legs stay short; failures print their full
log.

## Quick start

```sh
cd packages/typescript
bun install --frozen-lockfile
bun run check
```

Use the TypeScript CLI with a definition file:

```sh
npm install systemoneprompts
npx systemoneprompts generate triage.toml
```

## Repository map

- [`docs/SPEC.md`](docs/SPEC.md): language-neutral behavior.
- [`conformance/`](conformance/): shared behavior cases.
- [`packages/typescript/examples/`](packages/typescript/examples/): examples and inputs.
- [`packages/typescript/README.md`](packages/typescript/README.md): TypeScript API and CLI.
- [`packages/python/README.md`](packages/python/README.md): Python API and CLI.
- [`docs/releasing.md`](docs/releasing.md): release workflow.

Root checks are convenience wrappers:

```sh
make check
make check-conformance
```

Publishing is package-specific. The Makefile runs release checks first and
dry-runs by default:

```sh
make publish-typescript TYPESCRIPT_ARTIFACT=packages/typescript/systemoneprompts-0.1.0.tgz
make publish-python PYTHON_ARTIFACT=packages/python/dist/systemoneprompts-0.1.0-py3-none-any.whl
make publish-typescript TYPESCRIPT_ARTIFACT=... EXECUTE=1
```

Live provider tests are opt-in and require `TYPESAFE_API_KEY`.
