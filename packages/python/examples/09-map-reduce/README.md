# 09 — Map-reduce

`run_many` over many ticket states with the same questions, plus `eval --sweep` against labeled cases. Cache makes reruns free.

```bash
uv run python examples/09-map-reduce/run.py
uv run systemoneprompts eval examples/09-map-reduce/batch.toml --cases examples/09-map-reduce/cases.jsonl --cache --sweep urgent.yes
```
