import { describe, expect, test } from "bun:test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createCachingFetch, questionHash } from "../src/dev/cache.ts";
import {
  checkDefinition,
  DEFAULT_MODEL,
  generate,
  parseDefinition,
  readEnvModel,
  resolveModel,
} from "../src/index.ts";
import { fixture } from "./helpers.ts";

describe("resolveModel", () => {
  test("defaults to jev-latest", () => {
    expect(resolveModel()).toBe("jev-latest");
    expect(DEFAULT_MODEL).toBe("jev-latest");
  });

  test("later non-empty candidates win", () => {
    expect(resolveModel("jev-latest", "jev-2026-06")).toBe("jev-2026-06");
    expect(resolveModel(undefined, "from-toml", "from-call")).toBe("from-call");
    expect(resolveModel("from-env", "from-toml")).toBe("from-toml");
  });

  test("blank strings are ignored", () => {
    expect(resolveModel("jev-latest", "  ", "jev-1.13.0")).toBe("jev-1.13.0");
    expect(resolveModel("", undefined, null)).toBe(DEFAULT_MODEL);
  });
});

describe("readEnvModel", () => {
  test("blank TYPESAFE_MODEL falls back to TYPESAFE_DEFAULT_MODEL", () => {
    expect(readEnvModel({ TYPESAFE_MODEL: "  ", TYPESAFE_DEFAULT_MODEL: "jev-default" })).toBe(
      "jev-default",
    );
  });

  test("a non-blank TYPESAFE_MODEL wins", () => {
    expect(
      readEnvModel({ TYPESAFE_MODEL: "jev-explicit", TYPESAFE_DEFAULT_MODEL: "jev-default" }),
    ).toBe("jev-explicit");
  });
});

describe("TOML model field", () => {
  test("omitted model stays undefined on the definition", () => {
    const def = parseDefinition(fixture("golden/noul-string.toml"));
    expect(def.model).toBeUndefined();
  });

  test("generate always exports model; omitted stays undefined so TypeSafeClient defaults apply", () => {
    const omitted = generate(fixture("golden/noul-string.toml"), { filename: "noul-string.toml" });
    expect(omitted).toContain("export const model: string | undefined = undefined;");
    const pinned = generate(`model = "jev-2026-06"\n${fixture("golden/noul-string.toml")}`, {
      filename: "pinned.toml",
    });
    expect(pinned).toContain(`export const model = "jev-2026-06";`);
  });

  test("empty model is a compile error", () => {
    const def = parseDefinition(fixture("errors/empty-model.toml"), {
      filename: "empty-model.toml",
    });
    const error = checkDefinition(def).find((d) => d.code === "model-string");
    expect(error?.severity).toBe("error");
    expect(error?.message).toContain("non-empty string");
  });
});

describe("live-call model override", () => {
  test("cache keys include the requested model", () => {
    const state = { ticket: "hi" };
    const question = { type: "noul", instructions: "A?" };
    const latest = questionHash({ model: "jev-latest", state, question });
    const pinned = questionHash({ model: "jev-1.13.0", state, question });
    expect(latest).not.toBe(pinned);
  });

  test("interceptor forwards the call-site model, not the TOML default", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-model-"));
    let seen: string | undefined;
    const fetchImpl = createCachingFetch({
      dir,
      fetch: async (_input, init) => {
        const body = JSON.parse(String(init?.body)) as { model?: string };
        seen = body.model;
        return new Response(
          JSON.stringify({
            model: "jev-1.13.0",
            answers: { a: { type: "noul", noul: 0.9 } },
            usage: { input_tokens: 1, output_tokens: 1 },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      },
    });

    const tomlModel = "jev-latest";
    const callModel = resolveModel(tomlModel, "jev-1.13.0");
    await fetchImpl("https://api.typesafe.ai/v1/systemone", {
      method: "POST",
      body: JSON.stringify({
        model: callModel,
        state: {},
        questions: { a: { type: "noul", instructions: "A?" } },
      }),
    });
    expect(callModel).toBe("jev-1.13.0");
    expect(seen).toBe("jev-1.13.0");
  });
});
