import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import jpeg from "jpeg-js";
import { PNG } from "pngjs";
import { usedAssetReferences, validateAssetReferences, validateAssets } from "../src/assets.js";
import { TypeSafeClient } from "../src/client.js";
import { checkDefinition } from "../src/definition/check.js";
import { parseDefinition } from "../src/definition/parse.js";
import { createCachingFetch } from "../src/dev/cache.js";
import { imageAsset, loadAssets } from "../src/file-assets.js";

const nativeEnvKeys = ["CLOUDFLARE_ACCOUNT_ID", "TYPESAFE_BASE_URL"] as const;
const savedNativeEnv: Record<string, string | undefined> = {};
beforeEach(() => {
  for (const key of nativeEnvKeys) {
    savedNativeEnv[key] = process.env[key];
    delete process.env[key];
  }
});
afterEach(() => {
  for (const key of nativeEnvKeys) {
    if (savedNativeEnv[key] === undefined) delete process.env[key];
    else process.env[key] = savedNativeEnv[key];
  }
});

const headers = { "TypeSafe-Danger-Zone-Images": "true" };
const png = PNG.sync.write(new PNG({ width: 300, height: 300 }));
const asset = imageAsset(png);
const questions = { q: { type: "noul", instructions: "<asset:photo>" } } as const;

test("public client rejects malformed runtime image bytes before cache or transport", async () => {
  const dir = await mkdtemp(join(tmpdir(), "asset-preflight-"));
  let calls = 0;
  const caching = createCachingFetch({
    dir,
    fetch: async () => {
      calls++;
      throw new Error("transport called");
    },
  });
  const client = new TypeSafeClient({
    apiKey: "test",
    cloudflareAccountId: "",
    headers,
    fetch: caching,
  });
  const apng = await readFile(
    new URL("../../../conformance/v1/images/rectangle.png", import.meta.url),
  );
  // A single-frame acTL still declares animation and must fail even if a decoder ignores it.
  const animated = Buffer.concat([
    apng.subarray(0, 33),
    Buffer.from("000000086163544c000000010000000000000000", "hex"),
    apng.subarray(33),
  ]);
  for (const invalid of [
    { ...asset, data_base64: Buffer.from("not an image").toString("base64") },
    { ...asset, format: "jpg" },
    { ...asset, data_base64: png.subarray(0, -12).toString("base64") },
    { ...asset, data_base64: animated.toString("base64") },
    {
      ...asset,
      data_base64: PNG.sync.write(new PNG({ width: 279, height: 300 })).toString("base64"),
    },
  ])
    await expect(
      client.systemOne({ state: {}, questions, assets: { photo: invalid } } as never),
    ).rejects.toThrow();
  expect(calls).toBe(0);
  await rm(dir, { recursive: true, force: true });
});

test("valid PNG and JPEG aliases preserve exact runtime wire bytes", async () => {
  const jpg = jpeg.encode(
    { width: 300, height: 300, data: new Uint8Array(300 * 300 * 4) },
    80,
  ).data;
  const sent: any[] = [];
  const client = new TypeSafeClient({
    apiKey: "test",
    cloudflareAccountId: "",
    headers,
    fetch: async (_, init) => {
      sent.push(JSON.parse(String(init?.body)));
      return Response.json({
        model: "jev",
        answers: { q: { type: "noul", noul: 1 } },
        usage: { input_tokens: 1, output_tokens: 1 },
      });
    },
  });
  for (const input of [asset, imageAsset(jpg), { ...imageAsset(jpg), format: "jpeg" as const }]) {
    await client.systemOne({ state: {}, questions, assets: { photo: input } });
    expect(sent.at(-1).assets.photo).toEqual(input);
  }
});

test("native reference grammar and matching follow whole value priority and nonoverlap", () => {
  validateAssets({ "<photo>": asset });
  validateAssetReferences({ image: "<photo>" }, questions, { "<photo>": asset, photo: asset });
  validateAssetReferences("<photo>", { q: { type: "noul" } }, { "<photo>": asset });
  expect(usedAssetReferences(["category", "cat"], ["cat", "category"])).toEqual(
    new Set(["category", "cat"]),
  );
  expect(usedAssetReferences("abcde", ["abc", "bcd"])).toEqual(new Set(["abc"]));
  expect(() => usedAssetReferences("a category", ["cat", "category"])).toThrow("ambiguous");
  expect(() => validateAssetReferences("abcde", {}, { abc: asset, bcd: asset })).toThrow("unused");
  expect(() => validateAssetReferences({}, { photo: { type: "noul" } }, { photo: asset })).toThrow(
    "unused",
  );
  expect(() => validateAssets({ " ": asset })).toThrow("reference");
  expect(() => validateAssets({ ["é".repeat(513)]: asset })).toThrow("reference");
  expect(() => validateAssetReferences("<asset:missing>", {}, { "<photo>": asset })).toThrow(
    "missing",
  );
});

test("managed declarations reject invalid IDs and source combinations without loading files", async () => {
  for (const declaration of [
    '[assets.""]\nruntime=true',
    '[assets."<bad>"]\nruntime=true',
    '[assets.photo]\npath="   "',
    '[assets.photo]\npath="x"\nruntime=true',
    "[assets.photo]\nruntime=false",
    "[assets.photo]\npath=123",
  ]) {
    expect(
      parseDefinition(`${declaration}\n[questions.q]\ntype="noul"`).diagnostics.some(
        (d) => d.code === "asset-declaration",
      ),
    ).toBe(true);
  }
  const definition = parseDefinition(
    '[assets.photo]\npath="  literal.png"\n[questions.q]\ntype="noul"\ninstructions="<asset:photo>"',
  );
  expect(definition.assets.photo).toEqual({ path: "  literal.png" });
  await expect(loadAssets(definition)).rejects.toThrow("explicit filename or baseDir");
});

test("unknown asset diagnostics identify the actual literal question and field", () => {
  for (const field of [
    'instructions="<asset:missing>"',
    'criteria={true={example="<asset:missing>"}}',
  ]) {
    const source = `[questions.first]\ntype="noul"\ninstructions="fine"\n[questions."second.part"]\ntype="noul"\n${field}`;
    const diagnostic = checkDefinition(parseDefinition(source)).find(
      (d) => d.code === "asset-unknown-ref",
    );
    expect(diagnostic?.line).toBe(6);
  }
  const source =
    '[questions.first]\ntype="noul"\n[questions."second.part"]\ntype="noul"\n[questions."second.part".instructions]\nphoto="<asset:missing>"';
  expect(
    checkDefinition(parseDefinition(source)).find((d) => d.code === "asset-unknown-ref")?.line,
  ).toBe(5);
});

test("Box-only size validation includes the resolved model before transport", async () => {
  let calls = 0;
  const client = new TypeSafeClient({
    apiKey: "test",
    cloudflareAccountId: "",
    headers,
    defaultModel: "m".repeat(32 * 1024 * 1024),
    fetch: async () => {
      calls++;
      throw new Error("transport called");
    },
  });
  await expect(client.systemOne({ state: {}, questions: { q: { type: "box" } } })).rejects.toThrow(
    "32 MiB",
  );
  expect(calls).toBe(0);
});
