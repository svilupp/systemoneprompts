# Live tests

Live provider tests are outside the default package check. They require
`systemoneprompts[live]` and `TYPESAFE_API_KEY`. The offline parser/evaluator suite
must remain credential-free.

```bash
uv sync --locked --dev --extra live
TYPESAFE_API_KEY=... uv run --locked --extra live pytest live
```
