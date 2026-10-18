import { expect, test } from "bun:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CloudflareDecisionsClient } from "../src/cloudflare-decisions.js";
import { encodeDecisionsRequest as encodeCloudflare } from "../src/cloudflare-decisions-codec.js";
import type { CacheMode } from "../src/dev/cache.js";
import { createCachedCloudflareDecisionsClient } from "../src/dev/cloudflare-cache.js";
import { createCachedOpenAIDecisionsClient } from "../src/dev/openai-cache.js";
import type { SystemOneRequest } from "../src/native.js";
import { OpenAIDecisionsClient } from "../src/openai-decisions.js";
import { encodeDecisionsRequest as encodeOpenAI } from "../src/openai-decisions-codec.js";

const requests: SystemOneRequest[] = [
  {
    state: { photos: ["<asset:photo>"] },
    questions: { q: { type: "noul", instructions: "Inspect the photo" } },
  },
  { state: {}, questions: { q: { type: "noul", instructions: { evidence: ["<asset:photo>"] } } } },
  {
    state: {},
    questions: { q: { type: "noul", criteria: { true: { evidence: "<asset:photo>" } } } },
  },
];

for (const provider of ["openai", "cloudflare"] as const) {
  for (const mode of [undefined, "read-write", "read-only", "refresh"] as const) {
    test(`${provider} rejects reserved image references before ${mode ?? "network"}`, async () => {
      const dir = await mkdtemp(join(tmpdir(), "sop-provider-assets-"));
      let calls = 0;
      const fetch = async () => {
        calls++;
        throw new Error("transport must not be called");
      };
      const options = { apiKey: "test", fetch, maxRetries: 0 };
      const cachedOptions = { dir, mode: mode as CacheMode | undefined };
      const network =
        provider === "openai"
          ? new OpenAIDecisionsClient(options)
          : new CloudflareDecisionsClient({ ...options, accountId: "test" });
      const cached =
        mode === undefined
          ? undefined
          : provider === "openai"
            ? createCachedOpenAIDecisionsClient({
                ...cachedOptions,
                client: network as OpenAIDecisionsClient,
              })
            : createCachedCloudflareDecisionsClient({
                ...cachedOptions,
                client: network as CloudflareDecisionsClient,
              });
      try {
        for (const request of requests) {
          await expect((cached?.client ?? network).systemOne(request)).rejects.toMatchObject({
            kind: "compatibility",
            code: "images-compatibility",
          });
        }
        expect(calls).toBe(0);
        if (cached) expect(cached.cache.stats().requests).toBe(0);
      } finally {
        await rm(dir, { recursive: true, force: true });
      }
    });
  }

  test(`${provider} keeps reserved-looking object keys literal`, () => {
    const encode = provider === "openai" ? encodeOpenAI : encodeCloudflare;
    expect(
      encode(
        { "<asset:photo>": "plain text" },
        {
          q: {
            type: "choice",
            instructions: { "<asset:photo>": "plain text" },
            criteria: { "<asset:photo>": "first", other: "second" },
          },
        },
        provider === "openai" ? "gpt-6-luna" : "clef",
      ).ids,
    ).toEqual(["q"]);
  });
}
