# OpenAI ticket decisions

Use `OPENAI_API_KEY` to run the same native question types through Decisions.
From the package directory:

```sh
systemoneprompts run examples/11-openai-decisions/ticket.toml --state examples/11-openai-decisions/state.json --cache --json
systemoneprompts eval examples/11-openai-decisions/ticket.toml --cases examples/11-openai-decisions/cases.jsonl --report /tmp/openai-eval.json
```

The seven-case labeled sample covers three answer types, missing facts,
contradictory evidence, path references, and instruction-like content. Null labels
mean the evidence does not establish an expected answer. Its probabilities are observations,
not calibrated production thresholds. To compare TypeSafe, pass
`--provider typesafe --model jev-latest` and set `TYPESAFE_API_KEY`.

Run it twice to observe cache hits with zero usage. Inspect the same scope with
`systemoneprompts cache stats --provider openai`.
