# Provider fixtures

`openai-decisions.json` contains native requests, expected Decisions bodies,
provider responses, and normalized results or terminal error kinds. The mixed
success is based on the 2026-10-07 learning capture; reordered, fractional,
encoding-boundary, refusal, and malformed cases are synthetic. Extra usage
fields are intentionally ignored, while required counts remain validated.

`provider-selection.json` covers the reserved top-level TOML scalar. Focused
adapter tests load these files directly; wire cases stay outside the native
conformance manifest. Run `python3 tools/sync-shared.py` after edits.
