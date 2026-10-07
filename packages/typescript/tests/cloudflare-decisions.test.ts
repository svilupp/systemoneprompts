import { expect, test } from "bun:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createClient } from "../src/cli/io.js";
import {
  CacheMissError,
  cacheStats,
  cloudflareCacheDir,
  createCachedCloudflareDecisionsClient,
  createCachingFetch,
  questionHash,
} from "../src/dev/index.js";
import {
  CloudflareDecisionsClient,
  CloudflareDecisionsError,
  parseDefinition,
} from "../src/index.js";
import type { Questions } from "../src/native.js";
import { cli } from "./helpers.js";

const fixtures = JSON.parse(
  await readFile(
    new URL("../conformance/v1/providers/cloudflare-decisions.json", import.meta.url),
    "utf8",
  ),
);
const base = fixtures[0];
const defaults = { apiKey: "test-token", accountId: "test-account", maxRetries: 0 };
for (const fixture of fixtures) {
  test(`Cloudflare shared contract: ${fixture.name}`, async () => {
    let calls = 0;
    const client = new CloudflareDecisionsClient({
      ...defaults,
      defaultModel: fixture.model,
      fetch: async (url, init) => {
        calls++;
        expect(url).toBe(
          `https://api.cloudflare.com/client/v4/accounts/test-account/ai/run/@cf/cloudflare/${fixture.request.model}`,
        );
        expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer test-token");
        expect(JSON.parse(String(init?.body))).toEqual(fixture.request);
        return Response.json(fixture.response, { headers: { "cf-ray": "test-ray" } });
      },
    });
    const request = { state: fixture.state, questions: fixture.questions };
    if (fixture.error)
      await expect(client.systemOne(request)).rejects.toMatchObject({
        kind: fixture.error,
        body: fixture.response,
        requestId: "test-ray",
      });
    else expect(await client.systemOne(request)).toEqual(fixture.result);
    expect(calls).toBe(1);
  });
}

test("Cloudflare preflight rejects unsupported inputs without network", async () => {
  let calls = 0;
  const client = new CloudflareDecisionsClient({
    ...defaults,
    fetch: async () => {
      calls++;
      return Response.json({});
    },
  });
  for (const request of [
    { state: NaN, questions: base.questions },
    { state: {}, questions: {} },
    {
      state: {},
      questions: Object.fromEntries(
        Array.from({ length: 65 }, (_, i) => [String(i), { type: "noul" }]),
      ),
    },
    { state: {}, questions: base.questions, model: "jev-latest" },
    { state: {}, questions: base.questions, model: " " },
  ])
    await expect(client.systemOne(request)).rejects.toBeInstanceOf(CloudflareDecisionsError);
  expect(calls).toBe(0);
  expect(() => new CloudflareDecisionsClient({ ...defaults, fetch: createCachingFetch() })).toThrow(
    "cloudflare-cache-transport",
  );
});

test("Cloudflare preserves errors, retries transient HTTP, and rejects error envelopes", async () => {
  let calls = 0;
  const client = new CloudflareDecisionsClient({
    ...defaults,
    maxRetries: 1,
    fetch: async () => {
      calls++;
      return calls === 1
        ? Response.json(
            { errors: [{ message: "busy" }] },
            { status: 429, headers: { "retry-after": "0" } },
          )
        : Response.json(base.response);
    },
  });
  await client.systemOne({ state: base.state, questions: base.questions });
  expect(calls).toBe(2);
  for (const status of [200, 401]) {
    calls = 0;
    const failing = new CloudflareDecisionsClient({
      ...defaults,
      maxRetries: 2,
      fetch: async () => {
        calls++;
        return Response.json({ success: false, errors: [{ message: "denied" }] }, { status });
      },
    });
    await expect(failing.systemOne({ state: {}, questions: base.questions })).rejects.toMatchObject(
      { kind: "http", status: status === 200 ? 400 : status },
    );
    expect(calls).toBe(1);
  }
});

test("Cloudflare cache aliases, partial misses, validation, and isolation", async () => {
  const dir = await mkdtemp(join(tmpdir(), "clef-cache-"));
  const calls: any[] = [];
  const network = new CloudflareDecisionsClient({
    ...defaults,
    fetch: async (_url, init) => {
      const body = JSON.parse(String(init?.body));
      calls.push(body);
      const answers = Object.fromEntries(
        Object.entries(body.questions).map(([id, question]: [string, any]) => [
          id,
          Object.values(base.response.result.answers).find(
            (answer: any) => answer.type === question.type,
          ),
        ]),
      );
      return Response.json({
        success: true,
        result: { model: body.model, answers, usage: { input_tokens: 123, output_tokens: 0 } },
      });
    },
  });
  try {
    const made = createCachedCloudflareDecisionsClient({ client: network, dir });
    const request = { state: base.state, questions: base.questions as Questions };
    const firstId = Object.keys(request.questions)[0]!;
    await made.client.systemOne({
      ...request,
      questions: { [firstId]: request.questions[firstId]! },
    });
    const result = await made.client.systemOne(request);
    expect(Object.keys(calls[1].questions)).toEqual(["q0", "q1"]);
    const hit = await made.client.systemOne({ ...request, model: "@cf/cloudflare/clef" });
    expect(hit.answers).toEqual(result.answers);
    expect(hit.usage).toEqual({ input_tokens: 0, output_tokens: 0 });
    expect(calls).toHaveLength(2);
    await made.client.systemOne({ ...request, model: "clef-flash" });
    expect(calls).toHaveLength(3);
    expect((await cacheStats(made.cache.dir)).entries).toBe(6);
    const hash = questionHash({
      model: "clef",
      id: firstId,
      state: request.state,
      question: request.questions[firstId],
    });
    const path = join(made.cache.dir, hash.slice(0, 2), `${hash}.json`);
    const record = JSON.parse(await readFile(path, "utf8"));
    record.answer.noul = 2;
    await writeFile(path, JSON.stringify(record));
    const readonly = createCachedCloudflareDecisionsClient({
      client: network,
      dir,
      mode: "read-only",
    });
    await expect(readonly.client.systemOne(request)).rejects.toBeInstanceOf(CacheMissError);
    await made.client.systemOne(request);
    expect(Object.keys(calls[3].questions)).toHaveLength(1);
    expect(cloudflareCacheDir({ dir, accountId: "other-account" })).not.toBe(made.cache.dir);
    expect(cloudflareCacheDir({ dir, baseURL: `${network.baseURL}/` })).toBe(made.cache.dir);
    const stats = await cli([
      "cache",
      "stats",
      "--provider",
      "cloudflare",
      "--cache-root",
      dir,
      "--base-url",
      network.baseURL,
    ]);
    expect(stats.exitCode).toBe(0);
    expect(stats.stdout).toContain("entries  6");
    expect(
      (
        await cli([
          "cache",
          "clear",
          "--provider",
          "cloudflare",
          "--cache-root",
          dir,
          "--base-url",
          network.baseURL,
        ])
      ).exitCode,
    ).toBe(0);
    expect((await cacheStats(made.cache.dir)).entries).toBe(0);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("Cloudflare malformed live responses write no cache entries", async () => {
  const dir = await mkdtemp(join(tmpdir(), "clef-invalid-"));
  try {
    const network = new CloudflareDecisionsClient({
      ...defaults,
      fetch: async () =>
        Response.json(fixtures.find((f: any) => f.name === "invalid-score").response),
    });
    const made = createCachedCloudflareDecisionsClient({ client: network, dir });
    await expect(
      made.client.systemOne({ state: base.state, questions: base.questions }),
    ).rejects.toMatchObject({ kind: "response" });
    expect((await cacheStats(made.cache.dir)).entries).toBe(0);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("Cloudflare provider selection ignores unrelated settings and preserves pins", () => {
  const saved = { ...process.env };
  try {
    process.env.CLOUDFLARE_API_TOKEN = "test";
    process.env.CLOUDFLARE_ACCOUNT_ID = "test-account";
    process.env.TYPESAFE_BASE_URL = "https://other.invalid";
    process.env.TYPESAFE_MODEL = "jev-latest";
    const definition = parseDefinition(
      'provider="cloudflare"\nmodel="@cf/cloudflare/clef-flash"\n[questions.n]\ntype="noul"',
    );
    expect(createClient(definition, {}).model).toBe("clef-flash");
    expect(createClient(definition, { model: "clef" }).client).toBeInstanceOf(
      CloudflareDecisionsClient,
    );
  } finally {
    for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key];
    Object.assign(process.env, saved);
  }
});

const compatibility = JSON.parse(
  await readFile(
    new URL("../conformance/v1/providers/cloudflare-compatibility.json", import.meta.url),
    "utf8",
  ),
);
for (const fixture of compatibility)
  test(`Cloudflare compatibility: ${fixture.name}`, async () => {
    let calls = 0;
    const client = new CloudflareDecisionsClient({
      ...defaults,
      fetch: async () => {
        calls++;
        throw new Error("must not call network");
      },
    });
    await expect(
      client.systemOne({ state: {}, questions: fixture.questions }),
    ).rejects.toMatchObject({ kind: "compatibility", code: fixture.code });
    expect(calls).toBe(0);
  });

test("Cloudflare accepts 64 questions and propagates abort and timeout", async () => {
  const questions: Questions = Object.fromEntries(
    Array.from({ length: 64 }, (_, i) => [
      String(i),
      { type: "noul", instructions: "Is it true?" },
    ]),
  );
  const client = new CloudflareDecisionsClient({
    ...defaults,
    fetch: async (_url, init) => {
      const body = JSON.parse(String(init?.body));
      return Response.json({
        model: body.model,
        answers: Object.fromEntries(
          Object.keys(body.questions).map((id) => [id, { type: "noul", noul: 0.9 }]),
        ),
        usage: { input_tokens: 1, output_tokens: 0 },
      });
    },
  });
  expect(Object.keys((await client.systemOne({ state: {}, questions })).answers)).toHaveLength(64);
  const aborted = new AbortController();
  aborted.abort();
  await expect(
    client.systemOne({ state: {}, questions }, { signal: aborted.signal }),
  ).rejects.toMatchObject({ kind: "transport" });
  const slow = new CloudflareDecisionsClient({
    ...defaults,
    timeout: 1,
    fetch: async (_url, init) =>
      new Promise((_resolve, reject) =>
        init?.signal?.addEventListener("abort", () => reject(new TypeError("aborted")), {
          once: true,
        }),
      ),
  });
  await expect(slow.systemOne({ state: {}, questions })).rejects.toMatchObject({ kind: "timeout" });
});

test("Cloudflare retries preserve the original state and rubric", async () => {
  const state = { message: "original" };
  const criteria: [{ impact: string }, { impact: string }] = [
    { impact: "low" },
    { impact: "high" },
  ];
  const questions = { severity: { type: "score", instructions: "Rate impact", criteria } } as const;
  const calls: string[] = [];
  const client = new CloudflareDecisionsClient({
    ...defaults,
    maxRetries: 1,
    fetch: async (_url, init) => {
      calls.push(String(init?.body));
      if (calls.length === 1) {
        state.message = "changed";
        criteria[0].impact = "changed";
        return Response.json({}, { status: 429, headers: { "retry-after": "0" } });
      }
      return Response.json({
        model: "clef",
        usage: { input_tokens: 1, output_tokens: 0 },
        answers: {
          q0: {
            type: "score",
            score: 0.5,
            confidence: 0.2,
            probabilities: { "0": 0.5, "1": 0.5 },
            legend: { "0": { impact: "low" }, "1": { impact: "high" } },
          },
        },
      });
    },
  });
  const result = await client.systemOne({ state, questions });
  expect(calls).toHaveLength(2);
  expect(calls[1]).toBe(calls[0]);
  expect(result.answers.severity.legend["0"]).toEqual({ impact: "low" });
});

test("provider sample eval cases pass preflight without credentials", async () => {
  for (const example of ["11-openai-decisions", "12-cloudflare-decisions"]) {
    const result = await cli([
      "eval",
      `examples/${example}/ticket.toml`,
      "--cases",
      `examples/${example}/cases.jsonl`,
      "--provider",
      "invalid-after-case-validation",
    ]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("provider-value");
    expect(result.stderr).not.toContain("invalid eval case");
  }
});
