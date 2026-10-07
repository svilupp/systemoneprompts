# Provider fixtures

`openai-decisions.json` contains native requests, expected Decisions bodies,
provider responses, and normalized results or terminal error kinds. The mixed
success is based on the 2026-10-07 learning capture; reordered, fractional,
encoding-boundary, refusal, and malformed cases are synthetic. Extra usage
fields are intentionally ignored, while required counts remain validated.

`provider-selection.json` covers the reserved top-level TOML scalar. Focused
adapter tests load these files directly; wire cases stay outside the native
conformance manifest. Run `python3 tools/sync-shared.py` after edits.

`cloudflare-decisions.json` covers Clef wire requests, structured instructions and
criteria, opaque ID mapping, fractional Score legends, and whole-response validation.
`cloudflare-compatibility.json` covers local question/option/level limits and empty
Noul tasks. These synthetic fixtures are shared by both runtime adapters.

`make check-cache-parity` verifies that both runtimes read each other's OpenAI and
Cloudflare cache records and write identical record bytes under the same scopes.

`openrouter-decisions.json` preserves native questions and fractional answers for
Jev and Luna through the gateway. Provider-selection cases cover OpenRouter
and positioned endpoint diagnostics.
