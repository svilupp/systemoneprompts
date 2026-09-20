# Changelog

## Unreleased

- Python now depends on `pydantic` and `httpx2`; the optional `live` extra is removed.
## 0.1.0

- First Python release for shared TOML decision definitions.
- Validation, factors, clients, CLI tools, caching, and conformance checks.
- Documented OpenRouter via `base_url` / `TYPESAFE_BASE_URL`. Put the OpenRouter
  key in `TYPESAFE_API_KEY`.
- Cloudflare Workers AI via `cloudflare_account_id` / `CLOUDFLARE_ACCOUNT_ID`
  and `CLOUDFLARE_API_TOKEN`. Exclusive with `TYPESAFE_BASE_URL`.
