import { describe, expect, test } from "bun:test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CacheMissError, createCachingFetch } from "../src/dev/index.ts";
import {
  TypeSafeClient,
  TypeSafeClientError,
  TypeSafeHttpError,
  TypeSafeRateLimitError,
  TypeSafeTimeoutError,
} from "../src/index.ts";

const usage = { input_tokens: 1, output_tokens: 2 };
const noulAnswer = { type: "noul" as const, noul: 0.8 };

function jsonResponse(body: unknown, status = 200, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("TypeSafeClient", () => {
  test("requires an API key", () => {
    const previous = process.env.TYPESAFE_API_KEY;
    delete process.env.TYPESAFE_API_KEY;
    try {
      expect(() => new TypeSafeClient({ fetch: async () => jsonResponse({}) })).toThrow(
        TypeSafeClientError,
      );
    } finally {
      if (previous === undefined) delete process.env.TYPESAFE_API_KEY;
      else process.env.TYPESAFE_API_KEY = previous;
    }
  });

  test("posts System One JSON and returns the parsed body", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const client = new TypeSafeClient({
      apiKey: "test-key",
      baseURL: "https://api.example.test",
      defaultModel: "jev-test",
      maxRetries: 0,
      fetch: async (url, init) => {
        calls.push({ url, init });
        return jsonResponse({
          model: "jev-test",
          answers: { urgent: noulAnswer },
          usage,
        });
      },
    });
    const response = await client.systemOne({
      state: { text: "now" },
      questions: { urgent: { type: "noul", instructions: "Urgent?" } },
    });
    expect(response.answers.urgent.noul).toBe(0.8);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe("https://api.example.test/v1/systemone");
    const init = calls[0]?.init;
    expect(init?.method).toBe("POST");
    const headers = new Headers(init?.headers);
    expect(headers.get("authorization")).toBe("Bearer test-key");
    expect(JSON.parse(String(init?.body))).toEqual({
      state: { text: "now" },
      questions: { urgent: { type: "noul", instructions: "Urgent?" } },
      model: "jev-test",
    });
  });

  test("does not retry 400s", async () => {
    let calls = 0;
    const client = new TypeSafeClient({
      apiKey: "test",
      maxRetries: 2,
      fetch: async () => {
        calls += 1;
        return new Response("nope", { status: 400 });
      },
    });
    await expect(
      client.systemOne({ state: {}, questions: { q: { type: "noul" } } }),
    ).rejects.toBeInstanceOf(TypeSafeHttpError);
    expect(calls).toBe(1);
  });

  test("retries 509 then succeeds", async () => {
    let calls = 0;
    const client = new TypeSafeClient({
      apiKey: "test",
      maxRetries: 2,
      fetch: async () => {
        calls += 1;
        if (calls === 1) return new Response("busy", { status: 509 });
        return jsonResponse({ model: "jev-test", answers: { q: noulAnswer }, usage });
      },
    });
    const response = await client.systemOne({ state: null, questions: { q: { type: "noul" } } });
    expect(response.model).toBe("jev-test");
    expect(calls).toBe(2);
  });

  test("retries 503 then succeeds", async () => {
    let calls = 0;
    const client = new TypeSafeClient({
      apiKey: "test",
      maxRetries: 2,
      fetch: async () => {
        calls += 1;
        if (calls === 1) return new Response("busy", { status: 503 });
        return jsonResponse({ model: "jev-test", answers: { q: noulAnswer }, usage });
      },
    });
    const response = await client.systemOne({ state: null, questions: { q: { type: "noul" } } });
    expect(response.model).toBe("jev-test");
    expect(calls).toBe(2);
  });

  test("timeout covers a hanging response body", async () => {
    const client = new TypeSafeClient({
      apiKey: "test",
      timeout: 30,
      maxRetries: 0,
      fetch: async (_url, init) => {
        const stream = new ReadableStream({
          start(controller) {
            init?.signal?.addEventListener("abort", () => controller.error(new Error("aborted")), {
              once: true,
            });
          },
        });
        return new Response(stream, {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      },
    });
    await expect(
      client.systemOne({ state: {}, questions: { q: { type: "noul" } } }),
    ).rejects.toBeInstanceOf(TypeSafeTimeoutError);
  });

  test("late bodies that ignore abort still time out", async () => {
    const client = new TypeSafeClient({
      apiKey: "test",
      timeout: 20,
      maxRetries: 0,
      fetch: async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
        return jsonResponse({ model: "jev-test", answers: { q: noulAnswer }, usage });
      },
    });
    await expect(
      client.systemOne({ state: {}, questions: { q: { type: "noul" } } }),
    ).rejects.toBeInstanceOf(TypeSafeTimeoutError);
  });

  test("times out through a custom fetch", async () => {
    const client = new TypeSafeClient({
      apiKey: "test",
      timeout: 20,
      maxRetries: 0,
      fetch: async (_url, init) => {
        await new Promise((_, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), {
            once: true,
          });
        });
        return jsonResponse({});
      },
    });
    await expect(
      client.systemOne({ state: {}, questions: { q: { type: "noul" } } }),
    ).rejects.toBeInstanceOf(TypeSafeTimeoutError);
  });

  test("empty questions are rejected before fetch", async () => {
    let calls = 0;
    const client = new TypeSafeClient({
      apiKey: "test",
      fetch: async () => {
        calls += 1;
        return jsonResponse({});
      },
    });
    await expect(client.systemOne({ state: {}, questions: {} })).rejects.toBeInstanceOf(
      TypeSafeClientError,
    );
    expect(calls).toBe(0);
  });

  test("429 with Retry-After throws TypeSafeRateLimitError", async () => {
    const client = new TypeSafeClient({
      apiKey: "test",
      maxRetries: 0,
      fetch: async () =>
        new Response("slow down", { status: 429, headers: { "Retry-After": "1" } }),
    });
    const error = await client
      .systemOne({ state: {}, questions: { q: { type: "noul" } } })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TypeSafeRateLimitError);
    expect(error).toBeInstanceOf(TypeSafeHttpError);
    expect((error as TypeSafeRateLimitError).retryAfter).toBeCloseTo(1);
  });

  test("parses HTTP-date Retry-After without sleeping", async () => {
    const when = new Date(Date.now() + 2000).toUTCString();
    const client = new TypeSafeClient({
      apiKey: "test",
      maxRetries: 0,
      fetch: async () => new Response("later", { status: 429, headers: { "Retry-After": when } }),
    });
    const error = await client
      .systemOne({ state: {}, questions: { q: { type: "noul" } } })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TypeSafeRateLimitError);
    const retryAfter = (error as TypeSafeRateLimitError).retryAfter;
    expect(retryAfter).toBeDefined();
    expect(Math.abs((retryAfter ?? 0) - 2)).toBeLessThanOrEqual(1);
  });

  test("Authorization wins over caller headers", async () => {
    const captured: { authorization: string | null } = { authorization: null };
    const client = new TypeSafeClient({
      apiKey: "real-key",
      headers: { Authorization: "Bearer other" },
      maxRetries: 0,
      fetch: async (_url, init) => {
        captured.authorization = new Headers(init?.headers).get("authorization");
        return jsonResponse({ model: "jev-test", answers: { q: noulAnswer }, usage });
      },
    });
    await client.systemOne({ state: {}, questions: { q: { type: "noul" } } });
    expect(captured.authorization).toBe("Bearer real-key");
  });

  test("client-owned headers win regardless of caller header casing", async () => {
    let sent: Headers | undefined;
    const client = new TypeSafeClient({
      apiKey: "real-key",
      headers: { "user-agent": "my-app/1.0", "x-app": "keep" },
      maxRetries: 0,
      fetch: async (_url, init) => {
        sent = new Headers(init?.headers);
        return jsonResponse({ model: "jev-test", answers: { q: noulAnswer }, usage });
      },
    });
    await client.systemOne(
      { state: {}, questions: { q: { type: "noul" } } },
      { headers: { authorization: "Bearer hijack", accept: "text/html" } },
    );
    expect(sent?.get("authorization")).toBe("Bearer real-key");
    expect(sent?.get("accept")).toBe("application/json");
    expect(sent?.get("user-agent")).toMatch(/^systemoneprompts\//);
    expect(sent?.get("x-app")).toBe("keep");
  });

  test("read-only cache misses surface as CacheMissError without retries", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cache-"));
    let networkCalls = 0;
    const client = new TypeSafeClient({
      apiKey: "test",
      maxRetries: 2,
      fetch: createCachingFetch({
        dir,
        mode: "read-only",
        fetch: async () => {
          networkCalls += 1;
          return jsonResponse({ model: "jev-test", answers: { q: noulAnswer }, usage });
        },
      }),
    });
    const started = Date.now();
    const error = await client
      .systemOne({ state: {}, questions: { q: { type: "noul" } } })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(CacheMissError);
    expect(error).toBeInstanceOf(TypeSafeClientError);
    expect((error as CacheMissError).ids).toEqual(["q"]);
    expect(networkCalls).toBe(0);
    expect(Date.now() - started).toBeLessThan(300);
  });
});
