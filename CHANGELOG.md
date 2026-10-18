# Changelog

## 0.3.0 - 2026-10-18

### Added

- Native TypeSafe JSON/base64 image assets and Jev 1.14 Box questions, with
  explicit experimental opt-in and local provider compatibility checks.
- Static TOML assets, declared runtime slots, content-addressed generated bundles,
  and whole-request image caching shared by TypeScript and Python.
- Presence plus Box examples, an opt-in live vision lane, and separate offline
  presence/IoU scoring for held-out localization data.

## 0.2.0 - 2026-10-07

### Added

- OpenAI Decisions, OpenRouter Decisions, and Cloudflare Clef/Clef Flash in both
  packages, with provider selection, endpoint overrides, examples, and live checks.
- Scoped per-question caching across providers, cache management, and
  cross-language cache parity checks.

### Changed

- TOML `provider` is reserved for `typesafe`, `openai`, `openrouter`, or `cloudflare`.
- Python requires `pydantic` and `httpx2`; the optional `live` extra is removed.

### Fixed

- Retry payload snapshots and sample evaluation labels.

## 0.1.0

- First release of the TypeScript and Python packages.
- Shared TOML definitions, validation, factors, clients, CLI tools, and conformance checks.
