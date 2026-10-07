# Releasing

Prepare both package versions and changelogs before publishing. The current
release candidate is 0.2.0; the packages publish independently.

```sh
node packages/typescript/scripts/release-prepare.mjs --version 0.2.0
python packages/python/scripts/release-prepare.py --version 0.2.0
```

Keep TypeScript's `CLIENT_VERSION` and Python's source-checkout version fallback
in `src/client.ts` and `src/systemoneprompts/client.py` aligned with their package
versions. Python's preparation script also updates `uv.lock`. Definition/example
metadata versions are independent of package versions.

Run these commands from the repository root after authenticating with npm and
PyPI:

1. Run `make check`.
2. Run `make publish-typescript`.
3. Run `make publish-python`.

The TypeScript release check packs the npm tarball and smokes it from
fresh npm and bun installs under both Node and Bun. The packages publish
independently to npm and PyPI.
