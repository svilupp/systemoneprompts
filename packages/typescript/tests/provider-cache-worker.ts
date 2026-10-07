// Invoked by the repository's cross-runtime cache check, not by unit discovery.

import {
  createCachedCloudflareDecisionsClient,
  createCachedOpenAIDecisionsClient,
} from "../src/dev/index.js";
import { CloudflareDecisionsClient, OpenAIDecisionsClient } from "../src/index.js";
import { canonicalJson } from "../src/json.js";
import { providerFixtures } from "./provider-fixtures.js";

const [dir, action, provider] = process.argv.slice(2);
if (!dir || !action || !["openai", "cloudflare"].includes(provider ?? ""))
  throw new Error("dir, write/read, and openai/cloudflare required");
const cloudflare = provider === "cloudflare";
const fixture = providerFixtures(`${provider}-decisions`)[0];
let calls = 0;
const network = {
  apiKey: "fixture",
  fetch: async (url: string, init?: RequestInit) => {
    calls++;
    if (action !== "write") throw new Error("read-only called network");
    const endpoint = cloudflare
      ? "https://api.cloudflare.com/client/v4/accounts/fixture-account/ai/run/@cf/cloudflare/clef"
      : "https://api.openai.com/v1/decisions";
    if (url !== endpoint) throw new Error("wrong route");
    if (canonicalJson(JSON.parse(String(init?.body))) !== canonicalJson(fixture.request))
      throw new Error("wrong translated request");
    return Response.json(fixture.response);
  },
};
const options = {
  dir,
  mode: action === "write" ? ("read-write" as const) : ("read-only" as const),
};
const { client, cache } = cloudflare
  ? createCachedCloudflareDecisionsClient({
      ...options,
      client: new CloudflareDecisionsClient({ ...network, accountId: "fixture-account" }),
    })
  : createCachedOpenAIDecisionsClient({ ...options, client: new OpenAIDecisionsClient(network) });
const result = await client.systemOne({ state: fixture.state, questions: fixture.questions });
if (canonicalJson(result.answers) !== canonicalJson(fixture.result.answers))
  throw new Error("wrong normalized answers");
if (
  action === "read" &&
  (calls !== 0 || result.usage.input_tokens !== 0 || result.usage.output_tokens !== 0)
)
  throw new Error("read-only spent tokens");
console.log(JSON.stringify({ calls, stats: cache.stats() }));
