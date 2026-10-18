import { expect, test } from "bun:test";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { TypeSafeClient } from "../src/client.js";
import { createCachingFetch } from "../src/dev/cache.js";
import type { Assets } from "../src/native.js";
import { cli, root } from "./helpers.ts";

const questions = { q: { type: "noul" as const } };
const response = {
  model: "jev-test",
  answers: { q: { type: "noul", noul: 0.9 } },
  usage: { input_tokens: 1, output_tokens: 1 },
};
const optIn = "TypeSafe-Danger-Zone-Images";
async function image(name = "rectangle.png"): Promise<Assets[string]> {
  const data = await readFile(join(root, "conformance/v1/images", name));
  return {
    type: "image",
    format: name.endsWith("jpg") ? "jpg" : "png",
    data_base64: data.toString("base64"),
  };
}

test("empty client and bare cache asset maps share the ordinary text lane", async () => {
  const seen: unknown[] = [];
  const dir = await mkdtemp(join(tmpdir(), "sop-request-"));
  const caching = createCachingFetch({
    dir,
    fetch: async (_url, init) => {
      seen.push(JSON.parse(String(init?.body)));
      return Response.json(response);
    },
  });
  const client = new TypeSafeClient({ apiKey: "test", fetch: caching });
  await client.systemOne({ state: {}, questions, assets: {} });
  await client.systemOne({ state: {}, questions });
  await caching("https://api.typesafe.ai/v1/systemone", {
    method: "POST",
    body: JSON.stringify({ state: {}, questions, model: "jev-latest", assets: {} }),
  });
  expect(seen).toEqual([{ state: {}, questions, model: "jev-latest" }]);
});

for (const defaultOptIn of ["true", "false"]) {
  test(`case insensitive per-call headers override default ${defaultOptIn}`, async () => {
    const seen: Headers[] = [];
    const assets = { "<asset:photo>": await image() };
    const client = new TypeSafeClient({
      apiKey: "test",
      headers: { [optIn]: defaultOptIn, "X-Trace": "default" },
      fetch: async (_url, init) => {
        seen.push(new Headers(init?.headers));
        return Response.json(response);
      },
    });
    await expect(
      client.systemOne(
        { state: "<asset:photo>", questions, assets },
        { headers: { [optIn.toLowerCase()]: "false" } },
      ),
    ).rejects.toThrow("true is required");
    expect(seen).toHaveLength(0);
    await client.systemOne(
      { state: "<asset:photo>", questions, assets },
      {
        headers: {
          [optIn.toLowerCase()]: "true",
          "x-trace": "call",
          authorization: "hijack",
          "content-type": "text/plain",
        },
      },
    );
    expect(seen[0]?.get(optIn)).toBe("true");
    expect(seen[0]?.get("x-trace")).toBe("call");
    expect(seen[0]?.get("authorization")).toBe("Bearer test");
    expect(seen[0]?.get("content-type")).toBe("application/json");
  });
}

for (const invalid of [[], [1], false, null, "bad", 1]) {
  test(`eval rejects malformed shared assets ${JSON.stringify(invalid)} cleanly`, async () => {
    const dir = await mkdtemp(join(tmpdir(), "sop-eval-"));
    await writeFile(join(dir, "definition.toml"), '[questions.q]\ntype="noul"');
    await writeFile(join(dir, "cases.jsonl"), '{"state":{}}\n');
    await writeFile(join(dir, "assets.json"), JSON.stringify(invalid));
    const result = await cli([
      "eval",
      join(dir, "definition.toml"),
      "--cases",
      join(dir, "cases.jsonl"),
      "--assets",
      join(dir, "assets.json"),
    ]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("assets must be");
    expect(result.stderr).not.toContain("credentials");
  });
}

test("eval forwards shared bindings and per-case overrides to a local provider", async () => {
  const seen: { assets: Assets }[] = [];
  const server = Bun.serve({
    port: 0,
    hostname: "127.0.0.1",
    async fetch(request) {
      seen.push((await request.json()) as { assets: Assets });
      return Response.json(response);
    },
  });
  try {
    const dir = await mkdtemp(join(tmpdir(), "sop-eval-"));
    const shared = await image();
    const override = await image("rectangle.jpg");
    await writeFile(
      join(dir, "definition.toml"),
      '[assets.photo]\nruntime=true\n[questions.q]\ntype="noul"\ninstructions="Inspect <asset:photo>"',
    );
    await writeFile(join(dir, "assets.json"), JSON.stringify({ photo: shared }));
    await writeFile(
      join(dir, "cases.jsonl"),
      [
        { state: {}, labels: { q: true } },
        { state: {}, assets: { photo: override }, labels: { q: true } },
      ]
        .map((value) => JSON.stringify(value))
        .join("\n"),
    );
    const result = await cli(
      [
        "eval",
        join(dir, "definition.toml"),
        "--cases",
        join(dir, "cases.jsonl"),
        "--assets",
        join(dir, "assets.json"),
        "--experimental-images",
        "--base-url",
        server.url.toString(),
      ],
      { env: { TYPESAFE_API_KEY: "test" } },
    );
    expect(result.exitCode).toBe(0);
    expect(result.stderr).toBe("");
    expect(seen.map((request) => request.assets)).toEqual([
      { "<asset:photo>": shared },
      { "<asset:photo>": override },
    ]);
    expect(JSON.parse(result.stdout).questions.q.correct).toBe(2);
  } finally {
    server.stop(true);
  }
});

test("empty assets keep Box opt-in and malformed map checks", async () => {
  const client = new TypeSafeClient({
    apiKey: "test",
    fetch: async () => {
      throw new Error("network called");
    },
  });
  await expect(
    client.systemOne({ state: {}, questions: { q: { type: "box" } }, assets: {} }),
  ).rejects.toThrow("true is required");
  await expect(
    client.systemOne({ state: {}, questions, assets: [] as unknown as Assets }),
  ).rejects.toThrow();
});

for (const assetPath of ["empty", "missing"]) {
  test(`eval reads a shared ${assetPath} assets file`, async () => {
    const dir = await mkdtemp(join(tmpdir(), "sop-eval-"));
    await writeFile(join(dir, "definition.toml"), '[questions.q]\ntype="noul"');
    await writeFile(join(dir, "cases.jsonl"), '{"state":{}}\n');
    if (assetPath === "empty") await writeFile(join(dir, "assets.json"), "{}");
    const result = await cli(
      [
        "eval",
        join(dir, "definition.toml"),
        "--cases",
        join(dir, "cases.jsonl"),
        "--assets",
        join(dir, "assets.json"),
        "--provider",
        "openai",
      ],
      { env: { OPENAI_API_KEY: "", TYPESAFE_API_KEY: "" } },
    );
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain(assetPath === "empty" ? "OPENAI_API_KEY" : "assets.json");
  });
}
