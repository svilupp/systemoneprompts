# Provider fixtures

`native-decisions.json` is the small native Noul/Choice/Score sample used by
both languages, gateway tests, and every live provider probe.

`openai-decisions.json` and `cloudflare-decisions.json` each store one wire
baseline plus named field changes (`set` and `remove`, with key/index paths).
Test-only loaders expand these into independent cases. This retains encoding,
ID mapping, refusal, malformed-response, and fractional Score coverage without
repeating whole requests and responses.

The remaining small fixtures cover provider/endpoint selection, cache answer
validation, and Clef compatibility limits. They are consumed by both runtimes.
Package-local corpus paths link to this directory; edit only the canonical files.
`make check-cache-parity` verifies cross-runtime reads and identical record bytes.
