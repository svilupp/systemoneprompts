# v1 conformance corpus

This corpus is the language-neutral contract for parsers and evaluators. A
package may add implementation-specific tests, but the fixtures here must stay
valid TOML/JSON and must not depend on a runtime or provider.

Each case contains a `definition.toml`, optional `state.json`, optional
`answers.json`, and an `expected.json` result. Keep additions small and label
breaking changes with a new corpus version.

