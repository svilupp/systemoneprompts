import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CacheMissError, createCachingFetch } from "../src/dev/index.ts";
import {
  CLOUDFLARE_MODEL,
  createCloudflareFetch,
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
  const envKeys = [
    "TYPESAFE_API_KEY",
    "TYPESAFE_BASE_URL",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
  ] as const;
  const previousEnv: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const key of envKeys) {
      previousEnv[key] = process.env[key];
      delete process.env[key];
    }
  });

  afterEach(() => {
    for (const key of envKeys) {
      if (previousEnv[key] === undefined) delete process.env[key];
      else process.env[key] = previousEnv[key];
    }
  });

  test("requires an API key", () => {
    expect(() => new TypeSafeClient({ fetch: async () => jsonResponse({}) })).toThrow(
      TypeSafeClientError,
    );
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

  test("rejects Cloudflare mode combined with a custom base URL", () => {
    expect(
      () =>
        new TypeSafeClient({
          apiKey: "cf-token",
          cloudflareAccountId: "acct",
          baseURL: "https://openrouter.ai/api",
          fetch: async () => jsonResponse({}),
        }),
    ).toThrow(/cannot be combined with baseURL/);
  });

  test("Cloudflare mode requires a Cloudflare token", () => {
    expect(
      () =>
        new TypeSafeClient({
          cloudflareAccountId: "acct",
          fetch: async () => jsonResponse({}),
        }),
    ).toThrow(/CLOUDFLARE_API_TOKEN/);
  });

  test("empty apiKey falls back to CLOUDFLARE_API_TOKEN", async () => {
    process.env.CLOUDFLARE_API_TOKEN = "from-env";
    const auths: Array<string | null> = [];
    const client = new TypeSafeClient({
      apiKey: "",
      cloudflareAccountId: "acct-1",
      maxRetries: 0,
      fetch: async (_url, init) => {
        auths.push(new Headers(init?.headers).get("authorization"));
        return jsonResponse({
          success: true,
          result: {
            state: "Completed",
            result: { model: "jev-test", answers: { q: noulAnswer }, usage },
          },
        });
      },
    });
    await client.systemOne({ state: {}, questions: { q: { type: "noul" } } });
    expect(auths).toEqual(["Bearer from-env"]);
  });

  test("posts the Cloudflare envelope and unwraps result.result", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const client = new TypeSafeClient({
      apiKey: "cf-token",
      cloudflareAccountId: "acct-1",
      defaultModel: "jev-1.13.0",
      maxRetries: 0,
      fetch: async (url, init) => {
        calls.push({ url, init });
        return jsonResponse({
          success: true,
          errors: [],
          result: {
            state: "Completed",
            result: {
              model: "jev-1.13.0",
              answers: { urgent: noulAnswer },
              usage,
            },
            gatewayMetadata: { keySource: "BYOK" },
          },
        });
      },
    });
    const response = await client.systemOne({
      state: { text: "now" },
      questions: { urgent: { type: "noul", instructions: "Urgent?" } },
    });
    expect(response.model).toBe("jev-1.13.0");
    expect(response.answers.urgent.noul).toBe(0.8);
    expect(response).not.toHaveProperty("gatewayMetadata");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe("https://api.cloudflare.com/client/v4/accounts/acct-1/ai/run");
    expect(new Headers(calls[0]?.init?.headers).get("authorization")).toBe("Bearer cf-token");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      model: CLOUDFLARE_MODEL,
      input: {
        state: { text: "now" },
        questions: { urgent: { type: "noul", instructions: "Urgent?" } },
      },
    });
  });

  test("surfaces Cloudflare errors[].message", async () => {
    const client = new TypeSafeClient({
      apiKey: "cf-token",
      cloudflareAccountId: "acct-1",
      maxRetries: 0,
      fetch: async () =>
        jsonResponse(
          {
            success: false,
            errors: [
              {
                code: 2021,
                message: "Insufficient balance; add money to your gateway or use BYOK",
              },
            ],
            result: {},
          },
          402,
        ),
    });
    const error = await client
      .systemOne({ state: {}, questions: { q: { type: "noul" } } })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TypeSafeHttpError);
    expect((error as TypeSafeHttpError).status).toBe(402);
    expect((error as TypeSafeHttpError).message).toContain("Insufficient balance");
  });

  test("OpenRouter extra response fields pass through", async () => {
    const client = new TypeSafeClient({
      apiKey: "or-key",
      baseURL: "https://openrouter.ai/api",
      maxRetries: 0,
      fetch: async () =>
        jsonResponse({
          id: "gen-1",
          provider: "TypeSafe",
          model: "typesafe/jev-1.13",
          answers: { q: noulAnswer },
          usage: { ...usage, cost: 0.00001 },
        }),
    });
    const response = await client.systemOne({ state: "hi", questions: { q: { type: "noul" } } });
    expect(response.model).toBe("typesafe/jev-1.13");
    expect((response as { provider?: string }).provider).toBe("TypeSafe");
    expect(response.answers.q.noul).toBe(0.8);
  });

  test("cached Cloudflare misses still hash System One JSON", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cf-cache-"));
    const networkCalls: string[] = [];
    const network = async (url: string, init?: RequestInit) => {
      networkCalls.push(url);
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        input?: { questions?: Record<string, unknown> };
      };
      const ids = Object.keys(body.input?.questions ?? {});
      return jsonResponse({
        success: true,
        result: {
          state: "Completed",
          result: {
            model: "jev-1.13.0",
            answers: Object.fromEntries(ids.map((id) => [id, noulAnswer])),
            usage,
          },
        },
      });
    };
    const accountId = "acct-1";
    const client = new TypeSafeClient({
      apiKey: "cf-token",
      cloudflareAccountId: accountId,
      maxRetries: 0,
      fetch: createCachingFetch({
        dir,
        fetch: createCloudflareFetch({ accountId, fetch: network }),
      }),
    });
    const questions = {
      a: { type: "noul" as const },
      b: { type: "noul" as const },
    };
    const first = await client.systemOne({ state: "s", questions });
    expect(first.answers.a.noul).toBe(0.8);
    expect(networkCalls).toHaveLength(1);
    const second = await client.systemOne({ state: "s", questions: { a: questions.a } });
    expect(second.answers.a.noul).toBe(0.8);
    expect(networkCalls).toHaveLength(1);
  });

  test("rejects a caching fetch that does not wrap Cloudflare inside", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cf-cache-bare-"));
    expect(
      () =>
        new TypeSafeClient({
          apiKey: "cf-token",
          cloudflareAccountId: "acct",
          fetch: createCachingFetch({
            dir,
            fetch: async () =>
              jsonResponse({ model: "jev-test", answers: { q: noulAnswer }, usage }),
          }),
        }),
    ).toThrow(/wrapping Cloudflare inside the cache/);
  });

  test("preserves a Cloudflare 401 instead of rewriting it to 400", async () => {
    const client = new TypeSafeClient({
      apiKey: "cf-token",
      cloudflareAccountId: "acct-1",
      maxRetries: 0,
      fetch: async () =>
        jsonResponse(
          { success: false, errors: [{ code: 10000, message: "Authentication error" }] },
          401,
        ),
    });
    const error = await client
      .systemOne({ state: {}, questions: { q: { type: "noul" } } })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TypeSafeHttpError);
    expect((error as TypeSafeHttpError).status).toBe(401);
    expect((error as TypeSafeHttpError).message).toContain("Authentication error");
  });

  test("turns a 200 Cloudflare error envelope into 400", async () => {
    const client = new TypeSafeClient({
      apiKey: "cf-token",
      cloudflareAccountId: "acct-1",
      maxRetries: 0,
      fetch: async () => jsonResponse({ success: false, errors: [{ message: "nope" }] }),
    });
    const error = await client
      .systemOne({ state: {}, questions: { q: { type: "noul" } } })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TypeSafeHttpError);
    expect((error as TypeSafeHttpError).status).toBe(400);
  });

  test("turns a 200 Cloudflare insufficient-balance envelope into 402", async () => {
    const client = new TypeSafeClient({
      apiKey: "cf-token",
      cloudflareAccountId: "acct-1",
      maxRetries: 0,
      fetch: async () =>
        jsonResponse({ success: false, errors: [{ code: 2021, message: "Insufficient balance" }] }),
    });
    const error = await client
      .systemOne({ state: {}, questions: { q: { type: "noul" } } })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TypeSafeHttpError);
    expect((error as TypeSafeHttpError).status).toBe(402);
  });

  test("turns an incomplete Cloudflare job into 502", async () => {
    const client = new TypeSafeClient({
      apiKey: "cf-token",
      cloudflareAccountId: "acct-1",
      maxRetries: 0,
      fetch: async () => jsonResponse({ success: true, result: { state: "Running" } }),
    });
    const error = await client
      .systemOne({ state: {}, questions: { q: { type: "noul" } } })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TypeSafeHttpError);
    expect((error as TypeSafeHttpError).status).toBe(502);
  });

  test("rejects an unrecognized Cloudflare success envelope", async () => {
    const client = new TypeSafeClient({
      apiKey: "cf-token",
      cloudflareAccountId: "acct-1",
      maxRetries: 0,
      fetch: async () => jsonResponse({ success: true, result: { state: "Completed" } }),
    });
    const error = await client
      .systemOne({ state: {}, questions: { q: { type: "noul" } } })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TypeSafeHttpError);
    expect((error as TypeSafeHttpError).status).toBe(502);
  });

  test("reads Cloudflare mode from the environment", async () => {
    process.env.CLOUDFLARE_ACCOUNT_ID = "acct-env";
    process.env.CLOUDFLARE_API_TOKEN = "cf-env";
    const urls: string[] = [];
    const client = new TypeSafeClient({
      maxRetries: 0,
      fetch: async (url) => {
        urls.push(url);
        return jsonResponse({
          success: true,
          result: {
            state: "Completed",
            result: { model: "jev-test", answers: { q: noulAnswer }, usage },
          },
        });
      },
    });
    await client.systemOne({ state: {}, questions: { q: { type: "noul" } } });
    expect(urls[0]).toBe("https://api.cloudflare.com/client/v4/accounts/acct-env/ai/run");
  });
});
