// Invoked by the repository's cross-runtime cache check, not by unit discovery.

import { readFile } from "node:fs/promises";
import { createCachedCloudflareDecisionsClient } from "../src/dev/index.js";
import { CloudflareDecisionsClient } from "../src/index.js";
import { canonicalJson } from "../src/json.js";

const [dir, action] = process.argv.slice(2);
if (!dir || !action) throw new Error("dir and write/read required");
const fixture = JSON.parse(
  await readFile(
    new URL("../conformance/v1/providers/cloudflare-decisions.json", import.meta.url),
    "utf8",
  ),
)[0];
let calls = 0;
const raw = new CloudflareDecisionsClient({
  apiKey: "fixture",
  accountId: "fixture-account",
  fetch: async (url, init) => {
    calls++;
    if (action !== "write") throw new Error("read-only called network");
    if (
      url !==
      "https://api.cloudflare.com/client/v4/accounts/fixture-account/ai/run/@cf/cloudflare/clef"
    )
      throw new Error("wrong route");
    if (canonicalJson(JSON.parse(String(init?.body))) !== canonicalJson(fixture.request))
      throw new Error("wrong translated request");
    return Response.json(fixture.response);
  },
});
const { client, cache } = createCachedCloudflareDecisionsClient({
  client: raw,
  dir,
  mode: action === "write" ? "read-write" : "read-only",
});
const result = await client.systemOne({ state: fixture.state, questions: fixture.questions });
if (canonicalJson(result.answers) !== canonicalJson(fixture.result.answers))
  throw new Error("wrong normalized answers");
if (
  action === "read" &&
  (calls !== 0 || result.usage.input_tokens !== 0 || result.usage.output_tokens !== 0)
)
  throw new Error("read-only spent tokens");
console.log(JSON.stringify({ calls, stats: cache.stats() }));
