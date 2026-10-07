# Changelog

## Unreleased

## 0.2.0 - 2026-10-07

- Added `OpenAIDecisionsClient` and its error type, TOML `provider`, CLI
  `--provider`, and example 11 for all three answer types.
- Added OpenAI caching through the existing per-question interceptor, scoped
  cache management, and strict cache validation. Both runtimes share records.
- Added adapter fixtures, packed-consumer coverage, and opt-in live cache checks.
- Compatibility: top-level `provider` must now be `typesafe` or `openai`.
## 0.1.0

- First TypeScript release for TOML decision definitions.
- Validation, factors, clients, CLI tools, caching, and conformance checks.
- Documented OpenRouter via `baseURL` / `TYPESAFE_BASE_URL`. Put the OpenRouter
  key in `TYPESAFE_API_KEY`.
- Cloudflare Workers AI via `cloudflareAccountId` / `CLOUDFLARE_ACCOUNT_ID`
  and `CLOUDFLARE_API_TOKEN`. Exclusive with `TYPESAFE_BASE_URL`.
