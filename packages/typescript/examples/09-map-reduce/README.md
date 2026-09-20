# 09 — Map-reduce

`runMany` over many ticket states with the same questions, plus `eval --sweep` against labeled cases. Cache makes reruns free.

```bash
bun run examples/09-map-reduce/run.ts
systemoneprompts eval examples/09-map-reduce/batch.toml --cases examples/09-map-reduce/cases.jsonl --cache --sweep urgent.yes
```
