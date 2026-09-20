# TypeScript package guide

Read [`README.md`](README.md) for the format and CLI. Load
[`docs/skills/systemoneprompts/SKILL.md`](docs/skills/systemoneprompts/SKILL.md)
when authoring definitions or integrating the package.

Code map:

- `src/definition/`: TOML parsing, diagnostics, and cross-cutting checks.
- `src/questions/`, `src/state/`, `src/factors/`: native answers, state paths,
  and Boolean evaluation.
- `src/generate/`: deterministic TypeScript output.
- `src/cli/`: command dispatch and I/O.
- `tests/fixtures/`: golden output and one fixture per diagnostic.
- `examples/`: committed generated examples; use `examples:generate` after
  changing an input or the generator.

Keep TypeSafe question and answer shapes literal, diagnostics stable, generated
output deterministic, and source imports ESM with `.js` extensions. Runtime
code uses `smol-toml` and injected `fetch`; live tests are separate.

Default agent checks:

```sh
./scripts/run-quiet.sh "Checks" -- bun run check
./scripts/run-quiet.sh "Package smoke" -- bun run test:package
```

Use raw `bun test` or a named check leg only for focused debugging. Do not add
a build step to source-based tests and examples.
