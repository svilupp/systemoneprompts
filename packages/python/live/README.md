# Live provider checks

Export credentials for the providers to test, then run from this package:

```sh
sh scripts/run-quiet.sh "Live smoke" -- uv run --locked pytest live
```

Missing credentials skip that provider. Tests use the same small sample and
probe as the full matrix. See [provider testing](../../../docs/provider-live-validation.md)
for matrix options, credentials, and known limitations. Live requests are paid
and remain separate from deterministic checks.
