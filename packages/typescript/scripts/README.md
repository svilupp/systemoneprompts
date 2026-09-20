# TypeScript package scripts

These scripts are package-local so the package can be copied out of the repository and still be checked, built, packed, and release-validated.

`run-quiet.sh` is adapted from the `scripts/run-quiet` checks used by browser-pilot and flightplan. It retains full logs, keeps successful checks compact, and prints diagnostics when a leg fails.

- `check.mjs` runs all deterministic quality legs and accepts exact stage labels for a subset.
- `build.mjs` creates clean ESM output for Node 20+ and Bun, and marks the CLI executable.
- `package-smoke.mjs` packs the actual npm archive and installs it with both npm and bun, then imports and runs the CLI under Node and Bun.
- `release-check.mjs` runs the complete deterministic check and package smoke gate through `run-quiet.sh`.
- `release-prepare.mjs` updates the package version only.
- `publish.mjs` publishes the current package to npm; run `release:check` first.
