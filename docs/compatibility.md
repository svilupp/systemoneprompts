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
- In TypeSafe mode, `create_client(cache=True, transport=...)` routes misses through the caller's
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

## OpenAI Decisions and reserved provider scalar (2026-10-07)

`provider` is now reserved for `"typesafe"` and `"openai"`. Definitions that used
this scalar for other application metadata must move that value into `[data]`.
Definitions without `provider` retain identical generated output. Selected
providers appear only in generated `meta.provider`; questions, assertions, and
factors remain provider-independent. Concrete clients keep their explicit choice.

The optional OpenAI client uses the same native results and pattern interfaces.
Its strict whole-response validation is shared across languages. Single-option
Choice definitions remain valid for TypeSafe but fail OpenAI preflight with
`openai-choice-min-options`. Empty Noul tasks fail `openai-question-empty` and
explicit blank OpenAI models fail `openai-model-empty` before network I/O.
OpenAI caching now reuses the TypeSafe per-question interceptor and record format.
A private inner adapter translates only misses. Provider/version/endpoint
namespaces isolate observations; no existing TypeSafe hash or path changed.
An optional entry validator leaves the default cache behavior unchanged while
invalid OpenAI records become misses. Final validation rejects malformed merges.
`openai-cache-transport` replaces the initial unsupported-cache diagnostic for
incorrect raw transport composition; valid CLI `--cache` now works.

`make check-cache-parity` proves both runtimes read each other's records and
write byte-identical records under identical scoped paths. Deterministic tests
cover partial hits, zero-usage all hits, refresh/read-only modes, invalid records,
refusal, literal IDs, and scoped stats/clear. Packed consumer checks exercise the
dev factories as well as both concrete REST clients.

The [Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
and [API reference](https://developers.openai.com/api/reference/resources/decisions/methods/create)
were checked on 2026-10-07. The reference lists text field length constraints,
but does not establish upper question, option, or level counts. The adapter
never truncates or splits requests at guessed limits; the server validates its
remaining limits. Probabilities require application-specific calibration.

Both release suites and live cache smoke tests pass. The committed
[labeled sample](openai-decisions-sample.json) compares seven identical requests
on OpenAI and TypeSafe, including missing facts, contradictory evidence, path
references, and instruction-like content. The three unambiguous baseline cases
produce the expected department and Noul decision on both providers. Differences
are retained in the report: contradictory duplicate-charge evidence yields Noul
0.0 on OpenAI and 0.31 on TypeSafe; instruction-like ticket content yields shipping
probability 1.0 and 0.49 respectively. These are small-sample observations, not
calibration guarantees. Unknown sample labels remain null. Reproduce with
`uv run --locked python live/sample_openai.py --live --compare --report /tmp/decisions.json`
from the Python package; comparison requires both provider keys.

The [21-call-per-provider benchmark](provider-benchmark.md) records end-to-end
latencies, token usage, and current list-price estimates with local caching and
retries disabled. Its [raw report](provider-benchmark.json) retains all 42 calls.
