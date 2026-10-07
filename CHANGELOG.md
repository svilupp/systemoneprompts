# Changelog

## Unreleased

- Added OpenRouter Decisions for Jev and OpenAI models, gateway credentials,
  configurable base URLs, and isolated caches.

- Added Cloudflare Clef and Clef Flash with provider selection, JEV-compatible
  questions, scoped caching, and example 12 in both packages.
- Fixed retry payload snapshots and sample eval labels; clarified provider setup
  and cache documentation.

## 0.2.0 - 2026-10-07

- Added OpenAI Decisions clients for TypeScript and Python, with `gpt-6-luna`,
  TOML `provider`, and CLI `--provider` selection.
- Reused canonical per-question caching for OpenAI, including scoped stats/clear,
  strict cached-answer validation, and byte-identical cross-language records.
- Added shared fixtures, example 11, and live checks. Recorded 21 calls per
  provider with latencies and list-price costs in `docs/provider-benchmark.md`.
- Compatibility: top-level `provider` is now reserved for `typesafe` or `openai`.
- Python now depends on `pydantic` and `httpx2`; the optional `live` extra is removed.
- Documented OpenRouter via `TYPESAFE_BASE_URL` (`baseURL` / `base_url`). Put the
  OpenRouter key in `TYPESAFE_API_KEY`.
- Cloudflare Workers AI via `CLOUDFLARE_ACCOUNT_ID` (`cloudflareAccountId` /
  `cloudflare_account_id`) and `CLOUDFLARE_API_TOKEN`. Exclusive with
  `TYPESAFE_BASE_URL`.

## 0.1.0

- First release of the TypeScript and Python packages.
- Shared TOML definitions, validation, factors, clients, CLI tools, and conformance checks.
