# Releasing packages

Releases are package-scoped and artifact-based.

1. Run `make check` (or each package's local `check` command).
2. Run the package archive smoke test: `bun run test:package` for TypeScript
   and `uv run python scripts/package-smoke.py` for Python.
3. Prepare a version with the package-local release script and review the
   generated artifact: `bun run release:prepare -- --version <semver>` for
   TypeScript and `uv run python scripts/release-prepare.py --version <semver>`
   for Python. Then run `bun run release:check` or
   `uv run python scripts/release-check.py`.
4. Publish an explicitly named archive using the package-local publish script.
   Both scripts dry-run unless an execution flag is supplied.
5. Record the package version, conformance corpus version, and release notes.

No root command publishes both ecosystems implicitly. This keeps npm and PyPI
credentials, provenance, and rollback decisions independent.

