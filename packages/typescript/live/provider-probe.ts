/** One live provider variation; invoked by tools/run-live-providers.py. */
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  createCachedCloudflareDecisionsClient,
  createCachedOpenAIDecisionsClient,
  createCachingFetch,
  openRouterCacheDir,
} from "../src/dev/index.js";
import {
  CloudflareDecisionsClient,
  createCloudflareFetch,
  OpenAIDecisionsClient,
  partitionAnswers,
  TypeSafeClient,
} from "../src/index.js";
import type { Fetch, Questions } from "../src/native.js";
import type { SystemOneClient } from "../src/patterns/index.js";

const config = JSON.parse(await Bun.stdin.text());
const dir = await mkdtemp(join(tmpdir(), "provider-live-"));
let calls = 0;
const fetcher: Fetch = async (url, init) => {
  calls++;
  return fetch(url, init);
};
try {
  const explicit = config.mode === "explicit";
  const common = {
    fetch: fetcher,
    timeout: 20_000,
    maxRetries: 0,
    defaultModel: config.model,
    ...(explicit ? { apiKey: process.env[config.key], baseURL: config.baseURL } : {}),
  };
  let client: SystemOneClient;
  if (config.provider === "openai") {
    client = createCachedOpenAIDecisionsClient({
      client: new OpenAIDecisionsClient(common),
      dir,
    }).client;
  } else if (config.provider === "cloudflare") {
    client = createCachedCloudflareDecisionsClient({
      client: new CloudflareDecisionsClient(common),
      dir,
    }).client;
  } else {
    const cache = createCachingFetch({
      dir:
        config.provider === "openrouter"
          ? openRouterCacheDir({ dir, baseURL: config.baseURL })
          : join(dir, "cache"),
      fetch:
        config.provider === "cloudflare-jev"
          ? createCloudflareFetch({ accountId: process.env.CLOUDFLARE_ACCOUNT_ID!, fetch: fetcher })
          : fetcher,
    });
    client = new TypeSafeClient({
      ...common,
      fetch: cache,
      provider: config.provider === "openrouter" ? "openrouter" : "typesafe",
    });
  }
  const questions = config.questions as Questions;
  const request = { state: config.state, questions };
  const result = await client.systemOne(request);
  const hit = await client.systemOne(request);
  const partition = partitionAnswers(questions, result.answers);
  if (partition.missing.length || partition.malformed.length)
    throw new Error("Missing or malformed native answers");
  if (JSON.stringify(hit.answers) !== JSON.stringify(result.answers))
    throw new Error("Cached answers changed");
  if (hit.usage.input_tokens !== 0 || hit.usage.output_tokens !== 0 || calls !== 1)
    throw new Error("Cache did not eliminate repeated network call");
  console.log(
    JSON.stringify({
      status: "pass",
      model: result.model,
      usage: result.usage,
      answers: result.answers,
      networkCalls: calls,
    }),
  );
} catch (error) {
  const e = error as { name?: string; status?: number; kind?: string; message?: string };
  console.log(
    JSON.stringify({
      status: "fail",
      error: e.name,
      kind: e.kind,
      httpStatus: e.status,
      message: e.message,
    }),
  );
  process.exitCode = 1;
} finally {
  await rm(dir, { recursive: true, force: true });
}
