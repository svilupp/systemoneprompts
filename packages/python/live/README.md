# Live tests

Live provider tests are outside the default package check. They require
`TYPESAFE_API_KEY`. The offline parser/evaluator suite must remain
credential-free.

```bash
uv sync --locked --dev
TYPESAFE_API_KEY=... uv run --locked pytest live
```
