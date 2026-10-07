import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import endpointFixtures from "../conformance/v1/providers/endpoint-selection.json" with {
  type: "json",
};
import fixture from "../conformance/v1/providers/openrouter-decisions.json" with { type: "json" };
import { createClient } from "../src/cli/io.js";
import { createCachingFetch } from "../src/dev/cache.js";
import { OpenAIDecisionsClient, parseDefinition, TypeSafeClient } from "../src/index.js";
import type { Questions } from "../src/native.js";
import { openRouterBaseURL, openRouterCacheDir } from "../src/openrouter.js";

let previous: NodeJS.ProcessEnv;
beforeEach(() => {
  previous = { ...process.env };
  process.env.OPENROUTER_API_KEY = "router-key";
  delete process.env.OPENROUTER_BASE_URL;
  process.env.TYPESAFE_API_KEY = "native-key";
  process.env.TYPESAFE_BASE_URL = "https://native.invalid";
  process.env.CLOUDFLARE_ACCOUNT_ID = "ignored";
});
afterEach(() => {
  process.env = previous;
});

for (const model of fixture.models) {
  test(`OpenRouter native wire for ${model}`, async () => {
    let calls = 0;
    const client = new TypeSafeClient({
      provider: "openrouter",
      defaultModel: model,
      fetch: async (url, init) => {
        calls++;
        expect(url).toBe("https://openrouter.ai/api/alpha/decisions");
        expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer router-key");
        expect(JSON.parse(String(init?.body))).toEqual({
          state: fixture.state,
          questions: fixture.questions,
          model,
        });
        return Response.json(fixture.response);
      },
    });
    const response = await client.systemOne({
      state: fixture.state,
      questions: fixture.questions as Questions,
    });
    expect(response as unknown).toEqual(fixture.response);
    expect(calls).toBe(1);
  });
}

test("endpoint selection, key isolation, normalization and invalid TOML", () => {
  process.env.OPENROUTER_BASE_URL = " https://gateway.test/alpha/decisions/ ";
  const def = parseDefinition(
    'provider = "openrouter"\nbase_url = "https://toml.test/alpha"\nmodel = "openai/gpt-6-luna-decisions"\n[questions.q]\ntype = "noul"\ninstructions = "OK?"',
  );
  expect(def.baseURL).toBe("https://toml.test/alpha");
  expect(createClient(def, {}).client).toHaveProperty("baseURL", "https://toml.test/alpha");
  expect(createClient(def, { baseURL: "https://cli.test/alpha" }).client).toHaveProperty(
    "baseURL",
    "https://cli.test/alpha",
  );
  expect(new TypeSafeClient({ provider: "openrouter" }).baseURL).toBe("https://gateway.test/alpha");
  delete process.env.OPENROUTER_API_KEY;
  expect(() => new TypeSafeClient({ provider: "openrouter" })).toThrow("OPENROUTER_API_KEY");
  for (const value of [
    "",
    "ftp://host",
    "https://key@host",
    "https://host?key=secret",
    "https://host#part",
  ]) {
    expect(() => openRouterBaseURL(value)).toThrow();
    const parsed = parseDefinition(
      `base_url = ${JSON.stringify(value)}\n[questions.q]\ntype = "noul"`,
    );
    expect(parsed.diagnostics.some((d) => d.code === "base-url" && d.line === 1)).toBe(true);
  }
  process.env.OPENAI_API_KEY = "openai-key";
  process.env.OPENAI_BASE_URL = "https://direct.test/v1/decisions";
  expect(new OpenAIDecisionsClient().baseURL).toBe("https://direct.test/v1");
});

test("OpenRouter cache reuses native answers and isolates endpoints", async () => {
  const root = await mkdtemp(join(tmpdir(), "router-cache-"));
  try {
    const dir = openRouterCacheDir({ dir: root });
    expect(dir).toBe(
      openRouterCacheDir({ dir: root, baseURL: "https://openrouter.ai/api/alpha/decisions/" }),
    );
    expect(dir).not.toBe(openRouterCacheDir({ dir: root, baseURL: "https://other.test/alpha" }));
    let calls = 0;
    const cache = createCachingFetch({
      dir,
      fetch: async () => {
        calls++;
        return Response.json(fixture.response);
      },
    });
    const client = new TypeSafeClient({ provider: "openrouter", fetch: cache });
    const request = { state: fixture.state, questions: fixture.questions as Questions };
    await client.systemOne(request);
    const result = await client.systemOne(request);
    expect(calls).toBe(1);
    expect(result.answers as unknown).toEqual(fixture.response.answers);
    expect(result.usage.input_tokens).toBe(0);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("shared endpoint diagnostics", () => {
  for (const fixture of endpointFixtures) {
    const def = parseDefinition(fixture.source);
    expect(def.diagnostics.some((d) => d.code === "base-url" && d.line === 1)).toBe(true);
  }
});
