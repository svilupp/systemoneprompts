# Releasing 0.1.0

Run these commands from the repository root after authenticating with npm and
PyPI:

1. Run `make check`.
2. Run `make publish-typescript`.
3. Run `make publish-python`.

The TypeScript release check packs the npm tarball and smokes it from
fresh npm and bun installs under both Node and Bun. The packages publish
independently to npm and PyPI.
