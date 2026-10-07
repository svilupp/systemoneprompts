import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { createClient } from "../src/cli/io.js";
import {
  checkDefinition,
  OpenAIDecisionsClient,
  OpenAIDecisionsError,
  parseDefinition,
  TypeSafeClient,
} from "../src/index.js";
import type { Questions } from "../src/native.js";
import { runMany } from "../src/patterns/index.js";
import { providerFixtures } from "./provider-fixtures.js";

const fixtures = providerFixtures("openai-decisions");
for (const fixture of fixtures) {
  test(`Decisions shared fixture: ${fixture.name}`, async () => {
    let calls = 0;
    const client = new OpenAIDecisionsClient({
      apiKey: "openai-test",
      fetch: async (url, init) => {
        calls++;
        expect(url).toBe("https://api.openai.com/v1/decisions");
        expect(new Headers(init?.headers).get("authorization")).toBe("Bearer openai-test");
        expect(JSON.parse(String(init?.body))).toEqual(fixture.request);
        return Response.json(fixture.response, { headers: { "x-request-id": "req-test" } });
      },
    });
    if (fixture.error) {
      try {
        await client.systemOne(fixture);
        throw new Error("accepted malformed response");
      } catch (error) {
        expect(error).toBeInstanceOf(OpenAIDecisionsError);
        const failure = error as OpenAIDecisionsError;
        expect(failure.kind).toBe(fixture.error);
        expect(failure.body).toEqual(fixture.response);
        expect(failure.requestId).toBe("req-test");
        if (fixture.error === "refusal") expect(failure.refusedIds).toEqual(["charged.twice"]);
      }
    } else expect(await client.systemOne(fixture)).toEqual(fixture.result);
    expect(calls).toBe(1);
  });
}

test("canonical evidence, fallback, null descriptions and literal labels", async () => {
  const questions: Questions = JSON.parse(
    '{"__proto__":{"type":"choice","instructions":{},"criteria":{"__proto__":null,"constructor":{"é":[1e-7,1e21]}}},"s":{"type":"score","criteria":[null,[]]},"n":{"type":"noul","criteria":{"false":"no"}}}',
  );
  const client = new OpenAIDecisionsClient({
    apiKey: "test",
    maxRetries: 0,
    fetch: async (_, init) => {
      const body = JSON.parse(String(init?.body));
      expect(body.input).toBe('{"a":[true,null],"z":1e-7}');
      expect(body.questions[0].choices).toEqual([
        { value: "__proto__" },
        { value: "constructor", description: '{"é":[1e-7,1e+21]}' },
      ]);
      expect(body.questions[1].levels).toEqual([{ label: "0" }, { label: "1", description: "[]" }]);
      expect(body.questions[2].instructions).toBe(
        'Evaluate the supplied evidence against the criteria.\nOutcome criteria (JSON): {"false":"no"}',
      );
      return Response.json({
        model: "custom",
        usage: { input_tokens: 0, output_tokens: 0 },
        answers: [
          {
            name: "q0",
            type: "choice",
            choice: "__proto__",
            confidence: 0.4,
            probabilities: [
              { value: "__proto__", probability: 0.7 },
              { value: "constructor", probability: 0.2 },
            ],
          },
          {
            name: "q1",
            type: "score",
            score: 0.3,
            confidence: 0.8,
            probabilities: [
              { value: 0, probability: 0.7 },
              { value: 1, probability: 0.3 },
            ],
          },
          { name: "q2", type: "predicate", probability: 0.2 },
        ],
      });
    },
  });
  const result = await client.systemOne({ state: { z: 1e-7, a: [true, null] }, questions });
  expect(Object.hasOwn(result.answers, "__proto__")).toBe(true);
});

test("invalid requests fail without transport", async () => {
  let calls = 0;
  const client = new OpenAIDecisionsClient({
    apiKey: "test",
    fetch: async () => {
      calls++;
      throw new Error("network");
    },
  });
  for (const state of [NaN, new Date(), [undefined], Array(2), { x: undefined }]) {
    await expect(
      client.systemOne({ state, questions: { n: { type: "noul", instructions: "ok?" } } }),
    ).rejects.toMatchObject({ kind: "compatibility" });
  }
  for (const questions of [
    {},
    { n: { type: "noul" } },
    { c: { type: "choice", criteria: { only: null } } },
  ] as Questions[]) {
    await expect(client.systemOne({ state: null, questions })).rejects.toBeInstanceOf(
      OpenAIDecisionsError,
    );
  }
  await expect(
    client.systemOne({
      state: null,
      questions: { n: { type: "noul", instructions: "ok" } },
      model: " ",
    }),
  ).rejects.toMatchObject({ code: "openai-model-empty" });
  expect(() => new OpenAIDecisionsClient({ apiKey: "test", defaultModel: "" })).toThrow(
    "openai-model-empty",
  );
  expect(calls).toBe(0);
});

test("HTTP retries, request ID, owned headers and terminal 400", async () => {
  let calls = 0;
  const fixture = fixtures[0];
  const client = new OpenAIDecisionsClient({
    apiKey: "test",
    baseURL: "https://example.test/v1/decisions/",
    headers: { authorization: "wrong" },
    fetch: async (url, init) => {
      expect(url).toBe("https://example.test/v1/decisions");
      expect(new Headers(init?.headers).get("authorization")).toBe("Bearer test");
      return ++calls === 1
        ? Response.json({ error: "retry" }, { status: 429, headers: { "retry-after": "0" } })
        : Response.json(fixture.response);
    },
  });
  await client.systemOne(fixture, { headers: { AUTHORIZATION: "also wrong" } });
  expect(calls).toBe(2);
  const bad = new OpenAIDecisionsClient({
    apiKey: "test",
    fetch: async () => {
      calls++;
      return Response.json(
        { error: "bad" },
        { status: 400, headers: { "x-request-id": "req-bad", "retry-after": "99" } },
      );
    },
  });
  await expect(bad.systemOne(fixture)).rejects.toMatchObject({
    kind: "http",
    status: 400,
    requestId: "req-bad",
    retryAfter: 60,
  });
  expect(calls).toBe(3);
});

test("timeouts and cancellation stop requests", async () => {
  let calls = 0;
  const client = new OpenAIDecisionsClient({
    apiKey: "test",
    timeout: 5,
    maxRetries: 0,
    fetch: async (_, init) => {
      calls++;
      return await new Promise<Response>((_, reject) =>
        init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true }),
      );
    },
  });
  await expect(client.systemOne(fixtures[0])).rejects.toMatchObject({ kind: "timeout" });
  const controller = new AbortController();
  controller.abort();
  await expect(client.systemOne(fixtures[0], { signal: controller.signal })).rejects.toMatchObject({
    kind: "transport",
  });
  expect(calls).toBe(1);
});

const selections = JSON.parse(
  readFileSync(
    new URL("../conformance/v1/providers/provider-selection.json", import.meta.url),
    "utf8",
  ),
);
for (const fixture of selections)
  test(`provider setting ${fixture.source.split("\n")[0]}`, () => {
    const definition = parseDefinition(fixture.source);
    expect(checkDefinition(definition).some((d) => d.code === "provider-value")).toBe(
      !fixture.valid,
    );
    expect(definition.provider ?? null).toBe(fixture.provider);
    if (fixture.valid) expect(definition.meta.provider).toBe(fixture.provider);
  });

test("CLI construction precedence and environment isolation", () => {
  const old = { ...process.env };
  try {
    process.env.OPENAI_API_KEY = "openai-test";
    process.env.TYPESAFE_API_KEY = "typesafe-test";
    process.env.TYPESAFE_MODEL = "wrong-model";
    const definition = parseDefinition(
      'provider="openai"\n[questions.n]\ntype="noul"\ninstructions="ok?"',
    );
    expect(createClient(definition, {}).client).toBeInstanceOf(OpenAIDecisionsClient);
    expect(createClient(definition, {}).model).toBe("gpt-6-luna");
    expect(createClient(definition, { provider: "typesafe" }).client).toBeInstanceOf(
      TypeSafeClient,
    );
    expect(createClient(definition, { model: "custom" }).model).toBe("custom");
    definition.model = "jev-latest";
    expect(createClient(definition, {}).model).toBe("jev-latest");
  } finally {
    process.env = old;
  }
});

test("same processing code and patterns accept both clients", async () => {
  const questions = { n: { type: "noul", instructions: "ok?" } } as const;
  for (const Client of [TypeSafeClient, OpenAIDecisionsClient]) {
    let route = "";
    const client = new Client({
      apiKey: "test",
      fetch: async (url) => {
        route = url;
        return Response.json(
          Client === TypeSafeClient
            ? {
                model: "test",
                usage: { input_tokens: 1, output_tokens: 0 },
                answers: { n: { type: "noul", noul: 0.9 } },
              }
            : {
                model: "test",
                usage: { input_tokens: 1, output_tokens: 0 },
                answers: [{ name: "q0", type: "predicate", probability: 0.9 }],
              },
        );
      },
    });
    expect((await client.systemOne({ state: "ok", questions })).answers.n.noul).toBe(0.9);
    expect((await runMany(client, { questions, states: ["ok"] })).length).toBe(1);
    expect(route.endsWith(Client === TypeSafeClient ? "/v1/systemone" : "/v1/decisions")).toBe(
      true,
    );
  }
});

test("generic results retain exact choice labels and score legends", async () => {
  const client = new OpenAIDecisionsClient({
    apiKey: "test",
    fetch: async () =>
      Response.json({
        model: "test",
        usage: { input_tokens: 1, output_tokens: 0 },
        answers: [
          {
            name: "q0",
            type: "choice",
            choice: "yes",
            confidence: 0.8,
            probabilities: [
              { value: "yes", probability: 0.8 },
              { value: "no", probability: 0.2 },
            ],
          },
          {
            name: "q1",
            type: "score",
            score: 0.2,
            confidence: 0.7,
            probabilities: [
              { value: 0, probability: 0.8 },
              { value: 1, probability: 0.2 },
            ],
          },
        ],
      }),
  });
  const result = await client.systemOne({
    state: "OK",
    questions: {
      c: { type: "choice", criteria: { yes: null, no: null } },
      s: { type: "score", criteria: ["low", "high"] },
    } as const,
  });
  const choice: "yes" | "no" = result.answers.c.choice;
  const low: "low" = result.answers.s.legend["0"];
  // @ts-expect-error labels must not widen to arbitrary strings
  const invalid: "other" = result.answers.c.choice;
  expect([choice, low, invalid]).toEqual(["yes", "low", "yes"]);
});

test("OpenAI CLI preflight rejects blank model offline", async () => {
  const { cli } = await import("./helpers.js");
  const file = "examples/11-openai-decisions/ticket.toml";
  const state = "examples/11-openai-decisions/state.json";
  for (const [flags, message] of [
    [["--model", " "], "openai-model-empty"],
    [["--provider", "unknown"], "provider-value"],
  ] as const) {
    const result = await cli(["run", file, "--state", state, ...flags], {
      env: { OPENAI_API_KEY: "", TYPESAFE_API_KEY: "" },
    });
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain(message);
    expect(result.stderr).not.toContain("API_KEY");
  }
  expect(
    (await cli(["check", file], { env: { OPENAI_API_KEY: "", TYPESAFE_API_KEY: "" } })).exitCode,
  ).toBe(0);
  expect(
    (
      await cli(["generate", file, "--check"], {
        env: { OPENAI_API_KEY: "", TYPESAFE_API_KEY: "" },
      })
    ).exitCode,
  ).toBe(0);
});

test("taxonomy accepts either REST client", async () => {
  const { walkTaxonomy } = await import("../src/patterns/index.js");
  for (const Client of [TypeSafeClient, OpenAIDecisionsClient]) {
    const client = new Client({
      apiKey: "test",
      fetch: async () =>
        Response.json({
          model: "mock",
          usage: { input_tokens: 1, output_tokens: 0 },
          answers:
            Client === TypeSafeClient
              ? {
                  step: {
                    type: "choice",
                    choice: "A",
                    confidence: 0.8,
                    probabilities: { A: 0.8, B: 0.2 },
                  },
                }
              : [
                  {
                    name: "q0",
                    type: "choice",
                    choice: "A",
                    confidence: 0.8,
                    probabilities: [
                      { value: "A", probability: 0.8 },
                      { value: "B", probability: 0.2 },
                    ],
                  },
                ],
        }),
    });
    expect(
      await walkTaxonomy(client, { state: "evidence", tree: { A: "First", B: "Second" } }),
    ).toEqual([{ path: ["A"], probability: 0.8 }]);
  }
});
