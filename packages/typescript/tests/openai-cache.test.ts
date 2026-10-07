import { expect, test } from "bun:test";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  CacheMissError,
  cacheStats,
  createCachedOpenAIDecisionsClient,
  createCachingFetch,
  openAICacheDir,
  questionHash,
} from "../src/dev/index.js";
import { OpenAIDecisionsClient, OpenAIDecisionsError } from "../src/index.js";
import type { Questions } from "../src/native.js";
import { cli } from "./helpers.js";

const questions: Questions = JSON.parse(
  '{"__proto__":{"type":"noul","instructions":"Is it true?"},"c":{"type":"choice","criteria":{"__proto__":null,"constructor":"Other"}},"s":{"type":"score","criteria":["Low",{"description":"High"}]}}',
);
const literalId: string = "__proto__";
const state = { z: 1e-7, a: ["é", true, null] };
function mock(baseURL?: string) {
  const calls: any[] = [];
  let refuse = false;
  const client = new OpenAIDecisionsClient({
    apiKey: "test",
    baseURL,
    maxRetries: 0,
    fetch: async (_url, init) => {
      const body = JSON.parse(String(init?.body));
      calls.push(body);
      const answers = body.questions.map((q: any) => {
        if (refuse) return { type: "refusal", name: q.name };
        if (q.type === "predicate") return { type: q.type, name: q.name, probability: 0.8 };
        if (q.type === "choice")
          return {
            type: q.type,
            name: q.name,
            choice: q.choices[0].value,
            confidence: 0.6,
            probabilities: q.choices.map((c: any, i: number) => ({
              value: c.value,
              probability: i === 0 ? 0.8 : 0.2,
            })),
          };
        return {
          type: q.type,
          name: q.name,
          score: 0.2,
          confidence: 0.7,
          probabilities: q.levels.map((_: any, i: number) => ({
            value: i,
            probability: i === 0 ? 0.8 : 0.2,
          })),
        };
      });
      return Response.json({
        model: "reported",
        answers,
        usage: { input_tokens: 10, output_tokens: 0 },
      });
    },
  });
  return {
    client,
    calls,
    setRefusal: () => {
      refuse = true;
    },
  };
}
async function setup() {
  const dir = await mkdtemp(join(tmpdir(), "openai-cache-"));
  const network = mock();
  return { dir, network, ...createCachedOpenAIDecisionsClient({ client: network.client, dir }) };
}
function record(dir: string, id: string) {
  const hash = questionHash({ model: "gpt-6-luna", id, state, question: questions[id] });
  return join(dir, hash.slice(0, 2), `${hash}.json`);
}

test("cache intercepts canonical requests and splits misses with independent transport names", async () => {
  const { client, cache, network } = await setup();
  const first = await client.systemOne({
    state,
    questions: { [literalId]: questions[literalId]! },
  });
  const partial = await client.systemOne({ state, questions });
  const hit = await client.systemOne({ state, questions });
  expect(first.answers[literalId]!).toEqual(partial.answers[literalId]!);
  expect(network.calls).toHaveLength(2);
  expect(network.calls[1].questions.map((q: any) => [q.name, q.type])).toEqual([
    ["q0", "choice"],
    ["q1", "score"],
  ]);
  expect(hit.answers).toEqual(partial.answers);
  expect(hit.usage).toEqual({ input_tokens: 0, output_tokens: 0 });
  expect(partial.usage.input_tokens).toBe(10);
  expect(cache.stats()).toMatchObject({ requests: 3, hits: 4, misses: 3 });
  expect((await cacheStats(cache.dir)).entries).toBe(3);
});

test("invalid entries become misses and read-only misses are terminal", async () => {
  const { client, cache, network, dir } = await setup();
  await client.systemOne({ state, questions });
  const path = record(cache.dir, "s");
  const entry = JSON.parse(await readFile(path, "utf8"));
  entry.answer.legend = { 0: "wrong", 1: "wrong" };
  await writeFile(path, JSON.stringify(entry));
  const readOnly = createCachedOpenAIDecisionsClient({
    client: network.client,
    dir,
    mode: "read-only",
  });
  await expect(readOnly.client.systemOne({ state, questions })).rejects.toBeInstanceOf(
    CacheMissError,
  );
  expect(network.calls).toHaveLength(1);
  await client.systemOne({ state, questions });
  expect(network.calls[1].questions.map((q: any) => q.type)).toEqual(["score"]);
  const bad = JSON.parse(await readFile(record(cache.dir, "__proto__"), "utf8"));
  bad.answer.noul = 2;
  await writeFile(record(cache.dir, "__proto__"), JSON.stringify(bad));
  await client.systemOne({ state, questions });
  expect(network.calls[2].questions.map((q: any) => q.type)).toEqual(["predicate"]);
  await writeFile(record(cache.dir, "c"), "{malformed");
  await client.systemOne({ state, questions });
  expect(network.calls[3].questions.map((q: any) => q.type)).toEqual(["choice"]);
  const refreshed = createCachedOpenAIDecisionsClient({
    client: network.client,
    dir,
    mode: "refresh",
  });
  await refreshed.client.systemOne({ state, questions });
  expect(network.calls[4].questions).toHaveLength(3);
});

test("refused or malformed whole responses write no records", async () => {
  const { client, cache, network } = await setup();
  network.setRefusal();
  await expect(client.systemOne({ state, questions })).rejects.toMatchObject({ kind: "refusal" });
  expect((await cacheStats(cache.dir)).entries).toBe(0);
  expect(network.calls).toHaveLength(1);
  const dir = await mkdtemp(join(tmpdir(), "bad-openai-cache-"));
  let calls = 0;
  const raw = new OpenAIDecisionsClient({
    apiKey: "test",
    fetch: async () => {
      calls++;
      return Response.json({ model: "m", answers: [] });
    },
  });
  const bad = createCachedOpenAIDecisionsClient({ client: raw, dir });
  await expect(bad.client.systemOne({ state, questions })).rejects.toMatchObject({
    kind: "response",
  });
  expect(calls).toBe(1);
  expect((await cacheStats(bad.cache.dir)).entries).toBe(0);
});

test("provider/version/base URL isolation and CLI management use the same root", async () => {
  const { client, cache, network, dir } = await setup();
  await client.systemOne({ state, questions });
  expect(openAICacheDir({ dir, baseURL: "https://api.openai.com/v1/decisions/" })).toBe(cache.dir);
  const other = mock("https://other.test/v1/");
  const isolated = createCachedOpenAIDecisionsClient({
    client: other.client,
    dir,
    mode: "read-only",
  });
  await expect(isolated.client.systemOne({ state, questions })).rejects.toBeInstanceOf(
    CacheMissError,
  );
  expect(other.calls).toHaveLength(0);
  const stats = await cli(["cache", "stats", "--provider", "openai", "--cache-root", dir]);
  expect(stats.stdout).toContain("entries  3");
  const nativeDir = join(dir, "cache");
  await mkdir(nativeDir, { recursive: true });
  await writeFile(join(nativeDir, "sentinel"), "native");
  const versionDir = cache.dir.replace("/v1/", "/v2/");
  await mkdir(versionDir, { recursive: true });
  await writeFile(join(versionDir, "sentinel"), "v2");
  expect(
    (await cli(["cache", "clear", "--provider", "openai", "--cache-root", dir])).exitCode,
  ).toBe(0);
  expect(await readFile(join(nativeDir, "sentinel"), "utf8")).toBe("native");
  expect(await readFile(join(versionDir, "sentinel"), "utf8")).toBe("v2");
  expect((await cacheStats(cache.dir)).entries).toBe(0);
  expect(network.calls).toHaveLength(1);
});

test("warm hits still validate compatibility and bare caching fetch is rejected", async () => {
  const { client, network } = await setup();
  await client.systemOne({ state, questions });
  await expect(client.systemOne({ state, questions, model: " " })).rejects.toMatchObject({
    code: "openai-model-empty",
  });
  await expect(client.systemOne({ state: NaN, questions })).rejects.toMatchObject({
    kind: "compatibility",
  });
  expect(network.calls).toHaveLength(1);
  expect(() => new OpenAIDecisionsClient({ apiKey: "test", fetch: createCachingFetch() })).toThrow(
    OpenAIDecisionsError,
  );
});

test("shared strict validators cover cached answers and final merges", async () => {
  const { isValidDecisionsAnswer, validateNormalizedDecisionsResult } = await import(
    "../src/openai-decisions-codec.js"
  );
  const rows = JSON.parse(
    await readFile(
      new URL("../conformance/v1/providers/openai-cache-validation.json", import.meta.url),
      "utf8",
    ),
  );
  for (const row of rows) {
    expect(isValidDecisionsAnswer(row.question, row.answer)).toBe(row.valid);
    const result = {
      model: "cached",
      usage: { input_tokens: 0, output_tokens: 0 },
      answers: { q: row.answer },
    };
    if (row.valid)
      expect(validateNormalizedDecisionsResult(result, { q: row.question }).answers.q).toEqual(
        row.answer,
      );
    else
      expect(() => validateNormalizedDecisionsResult(result, { q: row.question })).toThrow(
        OpenAIDecisionsError,
      );
  }
});

test("cache origin rejects credentials and non-endpoint URL components", () => {
  for (const baseURL of [
    "https://user:secret@example.test/v1",
    "file:///tmp/v1",
    "https://example.test/v1?key=secret",
    "https://example.test/v1#fragment",
    "",
  ]) {
    expect(() => openAICacheDir({ baseURL })).toThrow(OpenAIDecisionsError);
  }
  expect(openAICacheDir({ baseURL: "https://example.test/v1/decisions/" })).toBe(
    openAICacheDir({ baseURL: "https://example.test/v1" }),
  );
});
