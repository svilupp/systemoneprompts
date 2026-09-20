import { describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CacheMissError, cacheStats, createCachingFetch, questionHash } from "../src/dev/index.ts";

const endpoint = "https://api.typesafe.ai/v1/systemone";

interface Body {
  model: string;
  answers: Record<string, unknown>;
  usage: { input_tokens: number; output_tokens: number };
}

function mockFetch(handler: (body: unknown) => unknown) {
  let calls = 0;
  const fetchImpl = async (_input: string, init?: RequestInit) => {
    calls += 1;
    const body = JSON.parse(String(init?.body));
    return new Response(JSON.stringify(handler(body)), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  return {
    fetchImpl,
    get calls() {
      return calls;
    },
  };
}

function request(questions: Record<string, unknown>): RequestInit {
  return {
    method: "POST",
    body: JSON.stringify({ model: "jev-latest", state: { ticket: "hi" }, questions }),
  };
}

describe("createCachingFetch", () => {
  test("hash is stable under key order", () => {
    const a = questionHash({
      model: "jev-latest",
      state: { b: 1, a: 2 },
      question: { type: "noul", instructions: "x", extra: false },
    });
    const b = questionHash({
      question: { extra: false, type: "noul", instructions: "x" },
      state: { a: 2, b: 1 },
      model: "jev-latest",
    });
    expect(a).toBe(b);
  });

  test("per-question invalidation, usage arithmetic, cumulative stats", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    const mock = mockFetch((body) => {
      const questions = (body as { questions: Record<string, unknown> }).questions;
      const answers = Object.fromEntries(
        Object.keys(questions).map((id) => [id, { type: "noul", noul: 0.9 }]),
      );
      return {
        model: "jev-2026-06",
        answers,
        usage: { input_tokens: 10 * Object.keys(questions).length, output_tokens: 2 },
      };
    });
    const fetchImpl = createCachingFetch({ dir, fetch: mock.fetchImpl });

    const a = { type: "noul", instructions: "A?" };
    const b = { type: "noul", instructions: "B?" };
    const bChanged = { type: "noul", instructions: "B changed?" };

    const first = (await (await fetchImpl(endpoint, request({ a, b }))).json()) as Body;
    expect(first.usage.input_tokens).toBe(20);
    expect(fetchImpl.stats()).toEqual({ requests: 1, hits: 0, misses: 2, keys: ["a", "b"] });
    const cacheFiles = await readdir(
      join(
        dir,
        questionHash({ model: "jev-latest", state: { ticket: "hi" }, question: a }).slice(0, 2),
      ),
    );
    expect(cacheFiles).toEqual(expect.arrayContaining([expect.stringMatching(/\.json$/)]));
    expect(cacheFiles.every((file) => file.endsWith(".json"))).toBe(true);

    const second = (await (await fetchImpl(endpoint, request({ a, b: bChanged }))).json()) as Body;
    expect(second.usage.input_tokens).toBe(10);
    expect(second.answers.a).toEqual({ type: "noul", noul: 0.9 });
    expect(fetchImpl.stats()).toMatchObject({ requests: 2, hits: 1, misses: 3 });
    expect(mock.calls).toBe(2);

    const third = (await (await fetchImpl(endpoint, request({ a, b: bChanged }))).json()) as Body;
    expect(third.usage.input_tokens).toBe(0);
    expect(third.model).toBe("jev-2026-06");
    expect(fetchImpl.stats()).toMatchObject({ requests: 3, hits: 3, misses: 3 });
    expect(mock.calls).toBe(2);
  });

  test("forwards malformed JSON bodies without intercepting them", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    let seenBody: unknown;
    const fetchImpl = createCachingFetch({
      dir,
      fetch: async (_input, init) => {
        seenBody = init?.body;
        return new Response("forwarded", { status: 200 });
      },
    });

    const init = { method: "POST", body: "{not-json" };
    const response = await fetchImpl(endpoint, init);

    expect(seenBody).toBe(init.body);
    expect(await response.text()).toBe("forwarded");
  });

  test("handles prototype-looking question ids safely", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    const mock = mockFetch((body) => {
      const questions = (body as { questions: Record<string, unknown> }).questions;
      return {
        model: "jev-latest",
        answers: Object.fromEntries(
          Object.keys(questions).map((id) => [id, { type: "noul", noul: 0.9 }]),
        ),
        usage: { input_tokens: 1, output_tokens: 1 },
      };
    });
    const fetchImpl = createCachingFetch({ dir, fetch: mock.fetchImpl });
    const questions = Object.create(null) as Record<string, unknown>;
    const prototypeQuestionId = "__proto__";
    questions[prototypeQuestionId] = { type: "noul", instructions: "A?" };

    const first = (await (await fetchImpl(endpoint, request(questions))).json()) as Body;
    const second = (await (await fetchImpl(endpoint, request(questions))).json()) as Body;

    expect(first.answers[prototypeQuestionId]).toEqual({ type: "noul", noul: 0.9 });
    expect(second.answers[prototypeQuestionId]).toEqual({ type: "noul", noul: 0.9 });
    expect(mock.calls).toBe(1);
  });

  test("corrupt cache records are misses, including in read-only mode", async () => {
    const question = { type: "noul", instructions: "A?" };
    const state = { ticket: "hi" };
    const hash = questionHash({ model: "jev-latest", state, question });
    const records: unknown[] = [
      null,
      [],
      "not-an-entry",
      { hash: "0".repeat(64), reportedModel: "jev-latest", answer: { type: "noul", noul: 0.9 } },
      { hash, reportedModel: "jev-latest" },
      { hash, reportedModel: "jev-latest", answer: null },
      { hash, reportedModel: "jev-latest", answer: {} },
    ];

    for (const record of records) {
      const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
      const shard = join(dir, hash.slice(0, 2));
      await mkdir(shard, { recursive: true });
      await writeFile(join(shard, `${hash}.json`), JSON.stringify(record));
      const fetchImpl = createCachingFetch({
        dir,
        mode: "read-only",
        fetch: async () => {
          throw new Error("network should not be called");
        },
      });

      await expect(
        fetchImpl(endpoint, {
          method: "POST",
          body: JSON.stringify({ model: "jev-latest", state, questions: { a: question } }),
        }),
      ).rejects.toThrow(/cache miss in read-only mode/);
    }
  });

  test("does not cache malformed successful responses", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    let calls = 0;
    const fetchImpl = createCachingFetch({
      dir,
      fetch: async () => {
        calls += 1;
        return new Response(
          JSON.stringify({
            model: "jev-latest",
            answers: { a: { type: "choice", choice: "wrong", confidence: 0.9 } },
          }),
          { status: 200, headers: { "x-typesafe-request-id": "req_bad" } },
        );
      },
    });
    const init = request({ a: { type: "noul", instructions: "A?" } });

    const first = await fetchImpl(endpoint, init);
    const second = await fetchImpl(endpoint, init);

    expect(first.headers.get("x-typesafe-request-id")).toBe("req_bad");
    expect(second.headers.get("x-typesafe-request-id")).toBe("req_bad");
    expect(calls).toBe(2);
    expect((await first.json()) as unknown).toEqual({
      model: "jev-latest",
      answers: { a: { type: "choice", choice: "wrong", confidence: 0.9 } },
    });
  });

  test("merges cached hits with only validated live answers", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    let calls = 0;
    const fetchImpl = createCachingFetch({
      dir,
      fetch: async (_input, init) => {
        calls += 1;
        const body = JSON.parse(String(init?.body)) as { questions: Record<string, unknown> };
        if (calls === 1) {
          return new Response(
            JSON.stringify({
              model: "jev-2026-06",
              answers: { cached: { type: "noul", noul: 0.8 } },
              usage: { input_tokens: 1, output_tokens: 1 },
            }),
          );
        }
        expect(Object.keys(body.questions)).toEqual(["live", "invalid", "missing"]);
        return new Response(
          JSON.stringify({
            model: "jev-2026-06",
            answers: {
              live: { type: "noul", noul: 0.7 },
              invalid: {
                type: "choice",
                choice: "wrong",
                confidence: 0.9,
                probabilities: { billing: 1, orders: 0 },
              },
            },
            usage: { input_tokens: 3, output_tokens: 2 },
          }),
          {
            status: 207,
            statusText: "Multi-Status",
            headers: { "x-typesafe-request-id": "req_partial" },
          },
        );
      },
    });

    const cached = { type: "noul", instructions: "cached?" };
    const live = { type: "noul", instructions: "live?" };
    const invalid = {
      type: "choice",
      instructions: "invalid?",
      criteria: { billing: "Billing", orders: "Orders" },
    };
    const missing = { type: "noul", instructions: "missing?" };

    await fetchImpl(endpoint, request({ cached }));
    const response = await fetchImpl(endpoint, request({ cached, live, invalid, missing }));
    const body = (await response.json()) as Body;

    expect(response.status).toBe(207);
    expect(response.statusText).toBe("Multi-Status");
    expect(response.headers.get("x-typesafe-request-id")).toBe("req_partial");
    expect(body.answers).toEqual({
      cached: { type: "noul", noul: 0.8 },
      live: { type: "noul", noul: 0.7 },
    });
    expect(body.usage).toEqual({ input_tokens: 3, output_tokens: 2 });

    const before = calls;
    const cachedLive = (await (
      await fetchImpl(endpoint, request({ cached, live }))
    ).json()) as Body;
    expect(cachedLive.answers).toEqual({
      cached: { type: "noul", noul: 0.8 },
      live: { type: "noul", noul: 0.7 },
    });
    expect(calls).toBe(before);
  });

  test("returns cached hits when the live response is not JSON", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    let calls = 0;
    const fetchImpl = createCachingFetch({
      dir,
      fetch: async () => {
        calls += 1;
        if (calls === 1) {
          return new Response(
            JSON.stringify({
              model: "jev-latest",
              answers: { cached: { type: "noul", noul: 0.8 } },
            }),
          );
        }
        return new Response("upstream exploded", {
          status: 200,
          headers: { "x-typesafe-request-id": "req_malformed" },
        });
      },
    });

    const cached = { type: "noul", instructions: "cached?" };
    const live = { type: "noul", instructions: "live?" };
    await fetchImpl(endpoint, request({ cached }));

    const response = await fetchImpl(endpoint, request({ cached, live }));
    expect(response.headers.get("x-typesafe-request-id")).toBe("req_malformed");
    expect(((await response.json()) as Body).answers).toEqual({
      cached: { type: "noul", noul: 0.8 },
    });
  });

  test("validates Choice and Score answers against their criteria", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    const mock = mockFetch((body) => {
      const questions = (body as { questions: Record<string, unknown> }).questions;
      const answers: Record<string, unknown> = {};
      if (questions.choice) {
        answers.choice = {
          type: "choice",
          choice: "billing",
          confidence: 0.8,
          probabilities: { billing: 0.8, orders: 0.1, extra: 0.1 },
          extra: "allowed",
        };
      }
      if (questions.score) {
        answers.score = {
          type: "score",
          score: 1.5,
          confidence: 0.6,
          legend: { "0": "Calm", "1": "Civil", "2": "Angry", extra: "allowed" },
          probabilities: { "0": 0.2, "1": 0.2, "2": 0.2, extra: 0.4 },
        };
      }
      return { model: "jev-latest", answers, usage: { input_tokens: 2, output_tokens: 1 } };
    });
    const fetchImpl = createCachingFetch({ dir, fetch: mock.fetchImpl });
    const questions = {
      choice: {
        type: "choice",
        instructions: "where?",
        criteria: { billing: "Billing", orders: "Orders" },
      },
      score: { type: "score", instructions: "how?", criteria: ["Calm", "Civil", "Angry"] },
    };

    const first = (await (await fetchImpl(endpoint, request(questions))).json()) as Body;
    const second = (await (await fetchImpl(endpoint, request(questions))).json()) as Body;

    expect(first.answers).toEqual(second.answers);
    expect(first.answers.choice).toEqual({
      type: "choice",
      choice: "billing",
      confidence: 0.8,
      probabilities: { billing: 0.8, orders: 0.1, extra: 0.1 },
      extra: "allowed",
    });
    expect(first.answers.score).toEqual({
      type: "score",
      score: 1.5,
      confidence: 0.6,
      legend: { "0": "Calm", "1": "Civil", "2": "Angry", extra: "allowed" },
      probabilities: { "0": 0.2, "1": 0.2, "2": 0.2, extra: 0.4 },
    });
    expect(mock.calls).toBe(1);
  });

  test("preserves successful response metadata and removes stale body headers", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    const fetchImpl = createCachingFetch({
      dir,
      fetch: async () =>
        new Response(
          JSON.stringify({
            model: "jev-2026-06",
            answers: { a: { type: "noul", noul: 0.9 } },
            usage: { input_tokens: 1, output_tokens: 1 },
          }),
          {
            status: 201,
            statusText: "Created",
            headers: {
              "content-type": "application/json; charset=utf-8",
              "content-length": "999",
              "content-encoding": "gzip",
              "x-typesafe-request-id": "req_42",
            },
          },
        ),
    });

    const response = await fetchImpl(
      endpoint,
      request({ a: { type: "noul", instructions: "A?" } }),
    );

    expect(response.status).toBe(201);
    expect(response.statusText).toBe("Created");
    expect(response.headers.get("x-typesafe-request-id")).toBe("req_42");
    expect(response.headers.get("content-length")).toBeNull();
    expect(response.headers.get("content-encoding")).toBeNull();
    expect(((await response.json()) as Body).answers.a).toEqual({ type: "noul", noul: 0.9 });
  });

  test("partial misses drop stale request Content-Length", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    const seen: Array<string | null> = [];
    const fetchImpl = createCachingFetch({
      dir,
      fetch: async (_url, init) => {
        seen.push(new Headers(init?.headers).get("content-length"));
        const body = JSON.parse(String(init?.body)) as {
          questions: Record<string, unknown>;
        };
        const answers = Object.fromEntries(
          Object.keys(body.questions).map((id) => [id, { type: "noul", noul: 0.9 }]),
        );
        return new Response(
          JSON.stringify({
            model: "jev-test",
            answers,
            usage: { input_tokens: 1, output_tokens: 1 },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      },
    });
    const a = { type: "noul", instructions: "A?" };
    const b = { type: "noul", instructions: "B?" };
    await fetchImpl(endpoint, {
      ...request({ a }),
      headers: { "content-length": "999" },
    });
    await fetchImpl(endpoint, {
      ...request({ a, b }),
      headers: { "content-length": "999" },
    });
    expect(seen.length).toBe(2);
    expect(seen[0]).toBeNull();
    expect(seen[1]).toBeNull();
  });

  test("cacheStats skips malformed files and uses a prototype-safe model map", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    const hash = "a".repeat(64);
    const shard = join(dir, hash.slice(0, 2));
    await mkdir(shard, { recursive: true });
    await writeFile(
      join(shard, `${hash}.json`),
      JSON.stringify({
        hash,
        requestedModel: "jev-latest",
        reportedModel: "__proto__",
        answer: { type: "noul", noul: 0.9 },
      }),
    );
    await writeFile(join(shard, "broken.json"), "not-json");
    await writeFile(join(shard, "array.json"), "[]");

    const stats = await cacheStats(dir);

    expect(stats.entries).toBe(1);
    const prototypeModel = "__proto__";
    expect(stats.models[prototypeModel]).toBe(1);
    expect(Object.getPrototypeOf(stats.models)).toBeNull();
  });

  test("cacheStats keeps distinct model drift tuples separate", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    const answer = { type: "noul", noul: 0.9 };
    const entries = [
      { requestedModel: "team→prod", reportedModel: "model" },
      { requestedModel: "team", reportedModel: "prod→model" },
      { requestedModel: undefined, reportedModel: "jev-latest" },
      { requestedModel: "", reportedModel: "jev-latest" },
    ];

    for (const [index, entry] of entries.entries()) {
      const hash = `${index}`.repeat(64);
      const shard = join(dir, hash.slice(0, 2));
      await mkdir(shard, { recursive: true });
      await writeFile(
        join(shard, `${hash}.json`),
        JSON.stringify({
          hash,
          ...(entry.requestedModel === undefined ? {} : { requestedModel: entry.requestedModel }),
          reportedModel: entry.reportedModel,
          answer,
        }),
      );
    }

    const stats = await cacheStats(dir);

    expect(stats.drift).toHaveLength(4);
    expect(stats.drift).toEqual(
      expect.arrayContaining([
        { requested: "team→prod", reported: "model", count: 1 },
        { requested: "team", reported: "prod→model", count: 1 },
        { reported: "jev-latest", count: 1 },
        { requested: "", reported: "jev-latest", count: 1 },
      ]),
    );
  });

  test("read-only miss is an error", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    const fetchImpl = createCachingFetch({
      dir,
      mode: "read-only",
      fetch: async () => {
        throw new Error("network should not be called");
      },
    });
    await expect(
      fetchImpl(endpoint, request({ a: { type: "noul", instructions: "A?" } })),
    ).rejects.toThrow(/cache miss in read-only mode/);
    await expect(
      fetchImpl(endpoint, request({ a: { type: "noul", instructions: "A?" } })),
    ).rejects.toBeInstanceOf(CacheMissError);
  });

  test("error responses pass through untouched and are not cached", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    let calls = 0;
    const fetchImpl = createCachingFetch({
      dir,
      fetch: async () => {
        calls += 1;
        return new Response("rate limited", {
          status: 429,
          headers: { "retry-after": "1", "x-typesafe-request-id": "req_1" },
        });
      },
    });
    const init = request({ a: { type: "noul", instructions: "A?" } });
    const response = await fetchImpl(endpoint, init);
    expect(response.status).toBe(429);
    expect(response.headers.get("x-typesafe-request-id")).toBe("req_1");
    expect(await response.text()).toBe("rate limited");
    await fetchImpl(endpoint, init);
    expect(calls).toBe(2);
  });

  test("non System One traffic is forwarded as-is", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    const fetchImpl = createCachingFetch({
      dir,
      fetch: async (input) => new Response(JSON.stringify({ url: input }), { status: 200 }),
    });
    const response = await fetchImpl("https://api.typesafe.ai/v1/models");
    expect(((await response.json()) as { url: string }).url).toContain("/v1/models");
  });
});
