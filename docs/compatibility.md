# Compatibility policy

The TOML definition format is versioned independently from package versions.
The `conformance/v1` corpus is the executable compatibility boundary.

- Additive fields and new examples may remain within `v1` when old fixtures
  keep their meaning.
- A changed diagnostic code, native question shape, factor truth table, or
  state assertion semantics requires a compatibility note and usually a new
  corpus version.
- Package-specific APIs may be idiomatic, but generated definitions must keep
  literal IDs, answer field names, and factor semantics identical.
- Deterministic checks must not contact TypeSafe. Live adapters are separate,
  opt-in commands and may be skipped when credentials are absent.

## TypeSafe / JEV HTTP client (2026-09-20)

Live commands use a native HTTP client. TypeScript uses global `fetch`.
Python depends on `pydantic` and `httpx2`.

| Item | Evidence |
| --- | --- |
| Auth | `TYPESAFE_API_KEY` as `Authorization: Bearer …`. Cloudflare mode uses `CLOUDFLARE_API_TOKEN` when `apiKey` / `api_key` is omitted. There is no `OPENROUTER_API_KEY` integration: pass the OpenRouter key as `apiKey` / `api_key`, or put it in `TYPESAFE_API_KEY` for CLI. |
| Base URL | `TYPESAFE_BASE_URL`, default `https://api.typesafe.ai`. OpenRouter: `https://openrouter.ai/api`. |
| Routing options | TypeScript `apiKey`, `baseURL`, `cloudflareAccountId`; Python `api_key`, `base_url`, `cloudflare_account_id`. |
| OpenRouter models | `jev-1.13` or `typesafe/jev-1.13` (not native `jev-latest` / `jev-1.13.0`). |
| Cloudflare | `CLOUDFLARE_ACCOUNT_ID` routes to `https://api.cloudflare.com/client/v4/accounts/{id}/ai/run` with `{ model: "typesafe/jev", input: { state, questions } }`. Unwraps a Workers AI envelope to `{ model, answers, usage }` whether `answers` is nested once or twice. Mutually exclusive with `TYPESAFE_BASE_URL`. TOML `model` and CLI `--model` do not change the catalog id. Token permission: Account → Workers AI → Read. |
| Native call | TypeScript `TypeSafeClient.systemOne({ state, questions, model })`; Python `await TypeSafeClient.system_one(state=..., questions=..., model=...)` |
| Response | Contract shape is `{ model, answers, usage }` with noul/choice/score objects. TypeScript leaves unknown JSON fields on the object; Python validation strips them (including `usage.cost`). |
| Cache hook | TypeScript intercepts `fetch`; Python wraps `httpx2.BaseTransport`. Same per-question cache records. Cloudflare rewrite sits inside the cache so keys stay System One JSON `{ state, questions, model }`. Passing a cache as `fetch` / `transport` without that inner wrap skips the rewrite. |
| Injected transport | TypeScript `new TypeSafeClient({ fetch, timeout })`; Python `TypeSafeClient(http_client=..., transport=..., timeout=...)` |
| Python pin | `pydantic>=2.13,<3` and `httpx2>=2.13,<3` |

The TypeScript package intercepts `fetch`. Python intercepts the HTTP transport
and writes the same per-question cache records (`hash`, `requestedModel`,
`reportedModel`, `answer`, serialized like `JSON.stringify(entry, null, 2)`), so
a cache directory written by either package is byte-identical and can be shared
in both directions. A request body without a `state` key hashes differently
from `state: null` in both packages.

Documented Python-only surfaces:

- Generated filename `<stem>_generated.py` versus TypeScript `<stem>.generated.ts`.
- `run --answers` remains an explicit offline CLI path.
- `run_many` / `walk_taxonomy` take a System One client, matching the TypeScript
  signatures (`beamWidth` validation name is preserved in errors). `run_many`
  captures `Exception` per item; `BaseException` (`KeyboardInterrupt`,
  `CancelledError`) propagates, where the TypeScript version catches everything.
- `create_client(cache=True, transport=...)` routes misses through the caller's
  transport; `cache=True` with a caller `http_client` is rejected
  (`cache-transport`) rather than silently uncached.

Known behavioural divergences from the TypeScript CLI:

- The Python client validates System One responses with pydantic before
  systemoneprompts evaluates factors. A malformed answer (for example a Score answer
  without `score`) fails the `eval` case at the provider step, so that case
  records no question statistics. The TypeScript CLI records question
  statistics first and then fails factor evaluation. Error counts and exit
  codes match; per-question totals can differ for such cases.
- Runtime-specific text differs where each language's parser speaks: TOML syntax
  messages (`tomllib` vs `smol-toml`), JSON parse errors, OS error strings, and
  argument-parser usage lines. Diagnostic codes, positions, and exit codes match.
