# Changelog

## 0.2.0 - 2026-10-07

### Added

- OpenAI Decisions, OpenRouter Decisions, and Cloudflare Clef/Clef Flash in both
  packages, with provider selection, endpoint overrides, examples, and live checks.
- Scoped per-question caching across providers, cache management, and
  cross-language cache parity checks.

### Changed

- TOML `provider` is reserved for `typesafe`, `openai`, `openrouter`, or `cloudflare`.

### Fixed

- Retry payload snapshots and sample evaluation labels.

## 0.1.0

- First TypeScript release for TOML decision definitions.
- Validation, factors, clients, CLI tools, caching, and conformance checks.
- Documented OpenRouter via `baseURL` / `TYPESAFE_BASE_URL`. Put the OpenRouter
  key in `TYPESAFE_API_KEY`.
- Cloudflare Workers AI via `cloudflareAccountId` / `CLOUDFLARE_ACCOUNT_ID`
  and `CLOUDFLARE_API_TOKEN`. Exclusive with `TYPESAFE_BASE_URL`.
