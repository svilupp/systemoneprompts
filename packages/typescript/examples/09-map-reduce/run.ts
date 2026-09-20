import { TypeSafeClient } from "systemoneprompts";
import { createCachingFetch } from "systemoneprompts/dev";
import { runMany } from "systemoneprompts/patterns";
import { model, questions } from "./batch.generated.ts";

const templates = [
  "I was charged twice for order A-{n}.",
  "Where is my order A-{n}?",
  "Reset my password, I cannot sign in.",
  "Please refund the duplicate charge.",
  "Cancel shipment A-{n} if it has not left.",
];

const states = Array.from({ length: 20 }, (_, i) => ({
  ticket: { message: templates[i % templates.length]!.replace("{n}", String(100 + i)) },
}));

const cache = createCachingFetch();
const client = new TypeSafeClient({ fetch: cache });
const results = await runMany(client, { questions, model, states, concurrency: 4 });

const counts = { billing: 0, orders: 0, account: 0, errors: 0 };
for (const result of results) {
  if (result instanceof Error) {
    counts.errors += 1;
    continue;
  }
  // `result.answers.topic.choice` is typed as the Choice labels from batch.toml.
  counts[result.answers.topic.choice] += 1;
}
console.log({ processed: results.length, counts, cache: cache.stats() });
