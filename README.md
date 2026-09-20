# systemoneprompts

Define TypeSafe questions, required state, and Boolean factors in TOML.
Validate definitions and generate typed modules for TypeScript or Python.

## Install

| Package | Command | Requires |
| --- | --- | --- |
| [TypeScript](packages/typescript/README.md) | `npm install systemoneprompts` or `bun add systemoneprompts` | Node 20+ or Bun |
| [Python](packages/python/README.md) | `pip install systemoneprompts` | Python 3.11+ |

Each package README includes a working example. Both packages ship the same
ten examples. Python API calls need `pip install 'systemoneprompts[live]'`.
Both clients use `TYPESAFE_API_KEY`.

## Development

Install dependencies from each package directory with
`bun install --frozen-lockfile` or `uv sync --locked --dev`. From the repository root:

```sh
make check
make release-check-typescript
make release-check-python
```

Checks use `scripts/run-quiet.sh`: short output on success, full logs on failure.
Live provider tests are separate.

Both packages follow the [v1 specification](docs/SPEC.md) and
[shared test cases](conformance/v1/). After editing shared files, run
`make sync-shared`.

## Publish

```sh
make publish-typescript
make publish-python
```

Each command runs release checks, builds, and uploads its package.
See [releasing](docs/releasing.md) for setup.
