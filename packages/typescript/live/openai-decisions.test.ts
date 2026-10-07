import { expect, test } from "bun:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadDotEnv } from "../src/cli/env.js";
import { createCachedOpenAIDecisionsClient } from "../src/dev/index.js";
import { OpenAIDecisionsClient, parseDefinition, partitionAnswers } from "../src/index.js";

loadDotEnv();
const gated = process.env.OPENAI_API_KEY ? test : test.skip;
gated("OpenAI Decisions all three native types", async () => {
  const root = new URL("../examples/11-openai-decisions/", import.meta.url);
  const definition = parseDefinition(await readFile(new URL("ticket.toml", root), "utf8"));
  const state = JSON.parse(await readFile(new URL("state.json", root), "utf8"));
  const dir = await mkdtemp(join(tmpdir(), "decisions-live-"));
  let calls = 0;
  const network = new OpenAIDecisionsClient({
    maxRetries: 0,
    fetch: async (url, init) => {
      calls++;
      return fetch(url, init);
    },
  });
  const { client, cache } = createCachedOpenAIDecisionsClient({ client: network, dir });
  try {
    const request = { state, questions: definition.questions };
    const result = await client.systemOne(request);
    const hit = await client.systemOne(request);
    const partition = partitionAnswers(definition.questions, result.answers);
    expect(partition.missing).toEqual([]);
    expect(partition.malformed).toEqual([]);
    expect(result.usage.output_tokens).toBe(0);
    expect(hit.answers).toEqual(result.answers);
    expect(hit.usage).toEqual({ input_tokens: 0, output_tokens: 0 });
    expect(calls).toBe(1);
    expect(cache.stats().hits).toBe(3);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
