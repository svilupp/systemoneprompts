# Cloudflare Clef decisions

Set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`, then run from the package directory:

```sh
systemoneprompts run examples/12-cloudflare-decisions/ticket.toml --state examples/12-cloudflare-decisions/state.json --cache --json
systemoneprompts run examples/12-cloudflare-decisions/ticket.toml --state examples/12-cloudflare-decisions/state.json --model clef-flash --cache --json
systemoneprompts eval examples/12-cloudflare-decisions/ticket.toml --cases examples/12-cloudflare-decisions/cases.jsonl --cache --report /tmp/clef-eval.json
systemoneprompts cache stats --provider cloudflare
```

Both models use the same Noul, Choice, and Score questions and factors. The seven
labeled cases are an evaluation sample; thresholds require validation on your data.
Full catalog IDs (`@cf/cloudflare/clef`, `@cf/cloudflare/clef-flash`) are aliases.
The cache separates Clef from Clef Flash and other providers. Repeat a request to
observe zero token usage on a cache hit.

## Run from this repository

The CLI reads only the current directory's `.env`. To use a shell-compatible
repository-root `.env`, run these commands from the repository root:

```sh
set -a
. ./.env
set +a
# Only when CLOUDFLARE_API_KEY already holds a Workers AI bearer token:
export CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-$CLOUDFLARE_API_KEY}"

# TypeScript source CLI
bun packages/typescript/src/cli/index.ts run packages/typescript/examples/12-cloudflare-decisions/ticket.toml --state packages/typescript/examples/12-cloudflare-decisions/state.json --model clef-flash --cache --json

# Python source CLI
uv run --locked --project packages/python systemoneprompts run packages/python/examples/12-cloudflare-decisions/ticket.toml --state packages/python/examples/12-cloudflare-decisions/state.json --model clef-flash --cache --json
```

`CLOUDFLARE_API_KEY` is a local name in this checkout, not an automatically read
setting. Global Cloudflare API keys are not supported; the client uses bearer-token
authentication. Programmatic clients require credentials in the process environment.
