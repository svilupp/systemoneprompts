import { expect, test } from "bun:test";
import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { isAnswerShape, isBoxCoordinates } from "../src/answers.js";
import { TypeSafeClient } from "../src/client.js";
import { cacheStats, clearCache, createCachingFetch } from "../src/dev/cache.js";

const box = {
  type: "box",
  box: { top: 0.1, bottom: 0.9, left: 0.2, right: 0.8 },
  confidence: null,
};
const questions = { q: { type: "box" as const } };
const request = { state: {}, questions, model: "jev-1.14.0" };
const headers = { "TypeSafe-Danger-Zone-Images": "true" };
const init = { method: "POST", headers, body: JSON.stringify(request) };
const endpoint = "https://native.example/v1/systemone";
const result = () => ({
  model: "jev-reported",
  answers: { q: structuredClone(box) },
  usage: { input_tokens: 2, output_tokens: 1 },
});
async function files(dir: string): Promise<string[]> {
  try {
    return (await readdir(dir, { withFileTypes: true })).flatMap((e) =>
      e.isFile() ? [join(dir, e.name)] : [],
    );
  } catch {
    return [];
  }
}
async function records(dir: string): Promise<string[]> {
  try {
    return (
      await Promise.all(
        (
          await readdir(dir, { withFileTypes: true })
        ).map((e) =>
          e.isDirectory() ? records(join(dir, e.name)) : Promise.resolve([join(dir, e.name)]),
        ),
      )
    ).flat();
  } catch {
    return [];
  }
}
async function temporary(run: (dir: string) => Promise<void>) {
  const dir = await mkdtemp(join(tmpdir(), "sop-contract-"));
  try {
    await run(dir);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

test("Box accepts nullable confidence and exactly four normalized ordered edges", () => {
  expect(isAnswerShape(box)).toBe(true);
  for (const confidence of [-1, 2, "0.5", Infinity])
    expect(isAnswerShape({ ...box, confidence })).toBe(false);
  for (const coordinates of [
    { ...box.box, extra: 3 },
    { ...box.box, top: 0.9 },
    { ...box.box, left: -0.1 },
  ])
    expect(isBoxCoordinates(coordinates)).toBe(false);
});

const malformed: Array<[string, (r: ReturnType<typeof result>) => unknown]> = [
  ["negative confidence", (r) => ({ ...r, answers: { q: { ...box, confidence: -1 } } })],
  ["high confidence", (r) => ({ ...r, answers: { q: { ...box, confidence: 2 } } })],
  [
    "extra coordinate",
    (r) => ({ ...r, answers: { q: { ...box, box: { ...box.box, extra: 3 } } } }),
  ],
  ["bad token type", (r) => ({ ...r, usage: { input_tokens: "bad", output_tokens: 1 } })],
  ["negative tokens", (r) => ({ ...r, usage: { input_tokens: 1, output_tokens: -1 } })],
  ["missing usage", (r) => ({ model: r.model, answers: r.answers })],
  ["missing answer", (r) => ({ ...r, answers: {} })],
  ["unexpected answer", (r) => ({ ...r, answers: { ...r.answers, extra: box } })],
  ["wrong answer type", (r) => ({ ...r, answers: { q: { type: "noul", noul: 1 } } })],
  ["blank model", (r) => ({ ...r, model: " " })],
];
for (const [name, mutate] of malformed)
  test(`image live/cache rejects ${name} before persistence`, async () =>
    temporary(async (dir) => {
      let calls = 0;
      const response = mutate(result());
      const caching = createCachingFetch({
        dir,
        fetch: async () => {
          calls++;
          return Response.json(response);
        },
      });
      for (let n = 0; n < 2; n++) await caching(endpoint, init);
      expect(calls).toBe(2);
      expect(await records(dir)).toEqual([]);
      const client = new TypeSafeClient({
        apiKey: "test",
        fetch: async () => Response.json(response),
        maxRetries: 0,
      });
      await expect(client.systemOne(request, { headers })).rejects.toThrow(
        "invalid System One response: image/Box contract",
      );
    }));

test("image disk validation turns malformed entries into misses and supports old records", async () =>
  temporary(async (dir) => {
    let calls = 0;
    const caching = createCachingFetch({
      dir,
      fetch: async () => {
        calls++;
        return Response.json(result());
      },
    });
    await caching(endpoint, init);
    const path = (await records(dir))[0]!;
    const record = JSON.parse(await readFile(path, "utf8"));
    delete record.requestedModel;
    await writeFile(path, JSON.stringify(record));
    expect(((await (await caching(endpoint, init)).json()) as { usage: unknown }).usage).toEqual({
      input_tokens: 0,
      output_tokens: 0,
    });
    expect(calls).toBe(1);
    expect(await cacheStats(dir)).toEqual({ entries: 1, models: { "jev-reported": 1 }, drift: [] });
    for (const [, mutate] of malformed) {
      const { model: _model, answers: _answers, usage: _usage, ...metadata } = record;
      await writeFile(path, JSON.stringify({ ...metadata, ...(mutate(result()) as object) }));
      const previousCalls = calls;
      await caching(endpoint, init);
      expect(calls).toBe(previousCalls + 1);
    }
  }));

test("disk stats count image requests and text questions once; clear preserves siblings", async () =>
  temporary(async (root) => {
    const dir = join(root, "cache");
    const caching = createCachingFetch({
      dir,
      fetch: async (_url, options) => {
        const payload = JSON.parse(String(options?.body));
        return Response.json(
          payload.questions.q.type === "box"
            ? { ...result(), answers: { ...result().answers, second: { type: "noul", noul: 1 } } }
            : {
                model: "text-reported",
                answers: { q: { type: "noul", noul: 1 } },
                usage: { input_tokens: 1, output_tokens: 1 },
              },
        );
      },
    });
    await caching(endpoint, {
      ...init,
      body: JSON.stringify({ ...request, questions: { ...questions, second: { type: "noul" } } }),
    });
    await caching(endpoint, {
      ...init,
      body: JSON.stringify({
        state: {},
        model: "text-requested",
        questions: { q: { type: "noul" } },
      }),
    });
    const stats = await cacheStats(dir);
    expect(stats.entries).toBe(2);
    expect(stats.models).toEqual({ "jev-reported": 1, "text-reported": 1 });
    expect(stats.drift).toContainEqual({
      requested: "jev-1.14.0",
      reported: "jev-reported",
      count: 1,
    });
    await mkdir(join(root, "unrelated"));
    await writeFile(join(root, "unrelated", "keep"), "keep");
    await clearCache(dir);
    expect(await records(dir)).toEqual([]);
    expect(await files(join(root, "unrelated"))).toHaveLength(1);
  }));

for (const url of ["https://openrouter.ai/api/alpha/decisions", "https://unknown.example/other"])
  test(`bare image cache rejects unsupported route ${url}`, async () =>
    temporary(async (dir) => {
      let calls = 0;
      const caching = createCachingFetch({
        dir,
        fetch: async () => {
          calls++;
          return Response.json(result());
        },
      });
      await expect(caching(url, init)).rejects.toThrow("native TypeSafe only");
      expect(calls).toBe(0);
      expect(await records(dir)).toEqual([]);
    }));

test("bare image cache rejects legacy Cloudflare before network", async () =>
  temporary(async (dir) => {
    let calls = 0;
    const network = Object.assign(
      async () => {
        calls++;
        return Response.json(result());
      },
      { systemonepromptsCloudflare: true },
    );
    await expect(createCachingFetch({ dir, fetch: network })(endpoint, init)).rejects.toThrow(
      "native TypeSafe only",
    );
    expect(calls).toBe(0);
    expect(await records(dir)).toEqual([]);
  }));

test("native image response validation uses the submitted question snapshot", async () => {
  const mutableRequest = structuredClone(request);
  const client = new TypeSafeClient({
    apiKey: "test",
    maxRetries: 0,
    fetch: async () => {
      (mutableRequest.questions.q as { type: string }).type = "noul";
      return Response.json(result());
    },
  });
  expect((await client.systemOne(mutableRequest, { headers })).answers.q.box).toEqual(box.box);
});
