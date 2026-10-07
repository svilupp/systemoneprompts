# Repository architecture

The repository has one language-neutral contract and one independently
operable directory per language.

```text
conformance/v1/              shared TOML/JSON behavior cases
docs/                        architecture, compatibility, release notes
packages/typescript/         primary npm package and reference implementation
packages/python/             Python port and wheel package
tools/                       repository-only synchronization checks
```

Each package owns its lockfile, local environment, source tree, tests, build,
quiet check wrapper, archive smoke test, and publish command. Root `make`
targets are orchestration convenience only; CI invokes package-local commands.

TypeScript is the reference where the specification is ambiguous. A behavior
change is complete only when the shared corpus and both package adapters agree.
Provider credentials belong to explicit live tests, never deterministic checks.

