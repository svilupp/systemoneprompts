# OpenAI Decisions and Jev benchmark

On 2026-10-07, both providers completed 21 of 21 calls. OpenAI had a lower median,
Jev had a lower p95, and their mean latencies were within 1 ms. Jev cost about
2.42 times less on this workload at published rates.

| Metric | OpenAI Decisions | Native TypeSafe |
| --- | ---: | ---: |
| Reported model | gpt-6-luna | jev-1.13.0 |
| Successful calls | 21/21 | 21/21 |
| Mean latency | 284.4 ms | 285.0 ms |
| Median latency | 234.2 ms | 255.0 ms |
| p95 latency | 405.8 ms | 345.0 ms |
| Min / max latency | 180.2 / 1267.1 ms | 215.6 / 645.0 ms |
| First call | 1267.1 ms | 309.8 ms |
| Median excluding first call | 233.5 ms | 253.5 ms |
| Total input tokens | 9,318 | 9,174 |
| Input price per million tokens | $0.10 | $0.042 |
| Output price | Free | Free |
| Estimated cost of 21 calls | $0.0009318 | $0.000385308 |
| Estimated cost per 1,000 requests | $0.04437 | $0.01835 |
| Estimated cost per 1,000 decisions | $0.01479 | $0.00612 |

Prices checked on 2026-10-07: [OpenAI Decisions pricing](https://developers.openai.com/api/docs/guides/decisions#pricing-and-availability)
and [TypeSafe model pricing](https://docs.typesafe.ai/models). OpenAI Decisions
charges input only, with no separate cache-read/write or output charges. Jev also
charges input only; its response reported output tokens, which are free. Costs
use each provider's reported input usage and standard list prices. They exclude
credits, discounts, taxes, regional premiums, and long-context multipliers.

The seven short ticket cases each ran three times with three questions per call:
Noul, Choice, and Score. Calls ran sequentially, alternating provider order for
each pair, through independent persistent HTTP clients. Both clients used their
native endpoints with local caching disabled, zero retries, and a 30-second
per-attempt timeout. Each provider received 21 network calls. Provider-side
caching was not controlled.

Latency measures `system_one` end to end with `perf_counter_ns`, including request
encoding, network time, parsing, and validation. First calls are included. p95
uses linear interpolation over successful observations. Measurements came from
the user's workstation with Europe/Prague timezone; network location was not
independently verified. Repeated cases are not 21 independent tasks, and this
sample does not establish production latency or throughput.

| Label check across repeated cases | OpenAI | Jev |
| --- | ---: | ---: |
| Noul correct at threshold 0.5 | 15/15 | 15/15 |
| Choice correct | 18/18 | 17/18 |
| Score mean absolute error | 0.0783 | 0.0150 |

Missing and contradictory binary labels are excluded. Score labels are ordinal
reference points; fractional expected scores are valid. These small-sample
checks do not establish calibration or general model quality.
