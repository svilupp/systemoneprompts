import { afterEach, beforeEach, expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import jpeg from "jpeg-js";
import { PNG } from "pngjs";
import { isAnswerForQuestion } from "../src/answers.js";
import { assetReferences, validateAssets } from "../src/assets.js";
import { TypeSafeClient } from "../src/client.js";
import { CloudflareDecisionsClient } from "../src/cloudflare-decisions.js";
import { checkDefinition } from "../src/definition/check.js";
import { loadDefinition, parseDefinition } from "../src/definition/parse.js";
import { createCachingFetch } from "../src/dev/cache.js";
import { createCachedCloudflareDecisionsClient } from "../src/dev/cloudflare-cache.js";
import { createCachedOpenAIDecisionsClient } from "../src/dev/openai-cache.js";
import { createFactorEvaluator, isKnownNativeAnswer } from "../src/factors/evaluate.js";
import {
  assetManifest,
  bundleDirectory,
  imageAsset,
  loadAssets,
  loadPackagedAssets,
} from "../src/file-assets.js";
import { generate, generateFile } from "../src/generate/generate.js";
import { canonicalJson } from "../src/json.js";
import type { Assets, Questions, SystemOneResult } from "../src/native.js";
import { OpenAIDecisionsClient } from "../src/openai-decisions.js";
import { runMany } from "../src/patterns/run-many.js";
import { walkTaxonomy } from "../src/patterns/walk-taxonomy.js";

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

const box = {
  type: "box",
  box: { top: 0, bottom: 1, left: 0.1, right: 0.9 },
  confidence: 0.9,
} as const;
const questions = { target: { type: "box", instructions: "Find <asset:photo>" } } as const;
const headers = { "TypeSafe-Danger-Zone-Images": "true" };
const pixels = () => new PNG({ width: 320, height: 320 });
const png = () => PNG.sync.write(pixels());
const asset = () => imageAsset(png());
const definition = `[assets.photo]\npath = "./images/é space.png"\n[questions.target]\ntype = "box"\ninstructions = "Find <asset:photo>"\n`;
const result = () =>
  Response.json({
    model: "jev-1.14.0",
    answers: { target: box },
    usage: { input_tokens: 1, output_tokens: 2 },
  });

async function temporary<T>(run: (dir: string) => Promise<T>): Promise<T> {
  const dir = await mkdtemp(join(tmpdir(), "sop vision "));
  try {
    return await run(dir);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

test("Box parses, generates typed native results, and rejects criteria or scalar factor assumptions", () => {
  const source =
    '[questions.target]\ntype="box"\ninstructions={ image="target" }\n[factors]\nknown={ref="target",known=true,confidence={gte=0.8}}';
  const def = parseDefinition(source);
  expect(checkDefinition(def)).toEqual([]);
  expect(generate(source)).toContain('type: "box"');
  const typed: SystemOneResult<typeof questions>["answers"]["target"] = box;
  expect(typed.box.left).toBe(0.1);
  for (const expression of [
    'all=["target"]',
    'ref="target",score={gte=1}',
    'ref="target",noul={gte=1}',
    'ref="target",choice="x"',
  ]) {
    expect(
      checkDefinition(
        parseDefinition(`[questions.target]\ntype="box"\n[factors]\ninvalid={${expression}}`),
      ).some((d) => d.severity === "error"),
    ).toBe(true);
  }
  expect(parseDefinition('[questions.target]\ntype="box"\ncriteria=[]').diagnostics[0]?.code).toBe(
    "box-criteria",
  );
});

test("Box geometry and nullable confidence follow known rules", () => {
  expect(isAnswerForQuestion({ type: "box" }, box)).toBe(true);
  for (const replacement of [
    { top: 1 },
    { left: 0.9 },
    { right: NaN },
    { bottom: 2 },
    { left: true },
  ]) {
    const malformed = { ...box, box: { ...box.box, ...replacement } };
    expect(isAnswerForQuestion({ type: "box" }, malformed)).toBe(false);
    expect(isKnownNativeAnswer(malformed)).toBe(false);
  }
  const unknown = { ...box, confidence: null };
  expect(isAnswerForQuestion({ type: "box" }, unknown)).toBe(true);
  expect(isKnownNativeAnswer(unknown)).toBe(false);
  const guarded = createFactorEvaluator({
    high: { ref: "target", known: true, confidence: { gte: 0.8 } },
  });
  expect(guarded({ target: unknown } as never).high).toBe(false);
  expect(() =>
    createFactorEvaluator({ high: { ref: "target", confidence: { gte: 0.8 } } })({
      target: unknown,
    } as never),
  ).toThrow("confidence");
});

test("wire asset shape and reserved refs validate values only", () => {
  validateAssets({ photo: asset() });
  expect(assetReferences({ "<asset:key>": ["<asset:photo>"] })).toEqual(new Set(["photo"]));
  for (const invalid of [
    { photo: { ...asset(), extra: true } },
    { photo: { ...asset(), data_base64: "@@==" } },
    { photo: { ...asset(), format: "gif" } },
  ])
    expect(() => validateAssets(invalid)).toThrow();
  expect(
    checkDefinition(parseDefinition('[questions.q]\ntype="noul"\ninstructions="<asset:typo>"'))[0]
      ?.code,
  ).toBe("asset-unknown-ref");
  expect(
    checkDefinition(
      parseDefinition('[assets.photo]\npath="image.png"\n[questions.q]\ntype="noul"'),
    ).filter((d) => d.severity === "error"),
  ).toEqual([]);
});

test("native client forwards identical snapshotted bytes on retry; images and boxes require opt-in", async () => {
  let calls = 0;
  const bodies: string[] = [];
  const request = {
    state: "<asset:photo>",
    questions,
    assets: { photo: asset() },
    model: "jev-1.14.0",
  };
  const client = new TypeSafeClient({
    apiKey: "test",
    headers,
    fetch: async (_, init) => {
      bodies.push(String(init?.body));
      request.assets.photo.data_base64 = "changed";
      if (++calls === 1) return Response.json({}, { status: 429, headers: { "retry-after": "0" } });
      return result();
    },
  });
  await client.systemOne(request);
  expect(bodies[0]).toBe(bodies[1]);
  expect(JSON.parse(bodies[0]!).assets.photo.type).toBe("image");
  await expect(
    new TypeSafeClient({
      apiKey: "test",
      fetch: async () => {
        throw new Error("network called");
      },
    }).systemOne({ state: "x", questions: { target: { type: "box" } } }),
  ).rejects.toThrow("Danger-Zone");
});

test("unsupported providers reject vision before network and cache", async () => {
  let calls = 0;
  const fetch = async () => {
    calls++;
    return result();
  };
  const request = { state: "<asset:photo>", questions, assets: { photo: asset() } };
  const openai = new OpenAIDecisionsClient({ apiKey: "test", fetch });
  const cloudflare = new CloudflareDecisionsClient({ apiKey: "test", accountId: "a", fetch });
  const clients = [
    openai,
    cloudflare,
    new TypeSafeClient({ apiKey: "test", provider: "openrouter", fetch }),
    new TypeSafeClient({ apiKey: "test", cloudflareAccountId: "a", fetch }),
    createCachedOpenAIDecisionsClient({ client: openai }).client,
    createCachedCloudflareDecisionsClient({ client: cloudflare }).client,
  ];
  for (const client of clients)
    await expect(client.systemOne(request)).rejects.toThrow("unsupported");
  expect(calls).toBe(0);
});

test("whole vision cache keys include all questions, map-order-independent assets and image bytes", async () =>
  temporary(async (dir) => {
    let calls = 0;
    const cache = createCachingFetch({
      dir,
      fetch: async (_, init) => {
        calls++;
        expect(Object.keys(JSON.parse(String(init?.body)).questions)).toEqual(["target"]);
        return result();
      },
    });
    const client = new TypeSafeClient({ apiKey: "test", headers, fetch: cache });
    const image = asset();
    const request = { state: "x", questions, assets: { photo: image } };
    await client.systemOne(request);
    await client.systemOne({
      ...request,
      assets: { photo: { data_base64: image.data_base64, format: image.format, type: image.type } },
    });
    expect(calls).toBe(1);
    await client.systemOne({ ...request, state: "changed" });
    const changed = pixels();
    changed.data[0] = 255;
    await client.systemOne({ ...request, assets: { photo: imageAsset(PNG.sync.write(changed)) } });
    expect(calls).toBe(3);
    const readonlyClient = new TypeSafeClient({
      apiKey: "test",
      headers,
      fetch: createCachingFetch({
        dir,
        mode: "read-only",
        fetch: async () => {
          throw new Error("network");
        },
      }),
    });
    expect((await readonlyClient.systemOne(request)).usage.input_tokens).toBe(0);
    await expect(readonlyClient.systemOne({ ...request, state: "miss" })).rejects.toThrow(
      "cache miss",
    );
  }));

test("malformed Box responses never enter vision cache", async () =>
  temporary(async (dir) => {
    let calls = 0;
    const client = new TypeSafeClient({
      apiKey: "test",
      headers,
      fetch: createCachingFetch({
        dir,
        fetch: async () => {
          calls++;
          return Response.json({
            model: "x",
            answers: { target: { ...box, box: { ...box.box, top: 1 } } },
            usage: { input_tokens: 1, output_tokens: 1 },
          });
        },
      }),
    });
    const request = { state: "x", questions, assets: { photo: asset() } };
    await expect(client.systemOne(request)).rejects.toThrow("invalid System One response");
    await expect(client.systemOne(request)).rejects.toThrow("invalid System One response");
    expect(calls).toBe(2);
  }));

test("file asset loader anchors lexical paths and snapshots bytes across cwd changes and symlinks", async () =>
  temporary(async (dir) => {
    await mkdir(join(dir, "images"));
    await writeFile(join(dir, "images", "é space.png"), png());
    await writeFile(join(dir, "source.toml"), definition);
    const def = await loadDefinition(join(dir, "source.toml"));
    const previous = process.cwd();
    let assets: Assets;
    try {
      process.chdir(tmpdir());
      assets = await loadAssets(def);
    } finally {
      process.chdir(previous);
    }
    await writeFile(join(dir, "images", "é space.png"), "corrupt");
    expect(assets["<asset:photo>"]?.data_base64).toBe(png().toString("base64"));
    await expect(loadAssets(parseDefinition(definition))).rejects.toThrow(
      "explicit filename or baseDir",
    );
    await writeFile(join(dir, "images", "é space.png"), png());
    expect(
      (await loadAssets(parseDefinition(definition), { baseDir: dir }))["<asset:photo>"],
    ).toEqual(assets["<asset:photo>"]);
    await mkdir(join(dir, "linked"));
    await symlink(join(dir, "source.toml"), join(dir, "linked", "alias.toml"));
    await expect(
      loadAssets(await loadDefinition(join(dir, "linked", "alias.toml"))),
    ).rejects.toThrow(join("linked", "images"));
    await mkdir(join(dir, "linked", "images"));
    await writeFile(join(dir, "linked", "images", "é space.png"), png());
    expect(
      (await loadAssets(await loadDefinition(join(dir, "linked", "alias.toml"))))["<asset:photo>"],
    ).toEqual(assets["<asset:photo>"]);
  }));

test("file image preflight decodes PNG/JPEG and rejects missing, corrupt, small and animated inputs", async () =>
  temporary(async (dir) => {
    expect(imageAsset(jpeg.encode(pixels(), 75).data).format).toBe("jpg");
    expect(() => imageAsset(png().subarray(0, 40))).toThrow();
    expect(() => imageAsset(jpeg.encode(pixels(), 75).data.subarray(0, 40))).toThrow();
    expect(() => imageAsset(PNG.sync.write(new PNG({ width: 279, height: 320 })))).toThrow(
      "280..1568",
    );
    const animated = Buffer.concat([
      png().subarray(0, 33),
      Buffer.from([0, 0, 0, 0, 97, 99, 84, 76, 0, 0, 0, 0]),
      png().subarray(33),
    ]);
    expect(() => imageAsset(animated)).toThrow("animated");
    const def = parseDefinition(definition, { baseDir: dir });
    await expect(loadAssets(def)).rejects.toThrow("resolved=");
    await mkdir(join(dir, "images", "é space.png"), { recursive: true });
    await expect(loadAssets(def)).rejects.toThrow("regular file");
  }));

test("runtime declarations require binding and prohibit static shadowing", async () => {
  const def = parseDefinition(
    '[assets.photo]\nruntime=true\n[questions.q]\ntype="box"\ninstructions="<asset:photo>"',
  );
  await expect(loadAssets(def)).rejects.toThrow("runtime binding");
  expect((await loadAssets(def, { runtimeAssets: { photo: asset() } }))["<asset:photo>"]).toEqual(
    asset(),
  );
  await expect(
    loadAssets(parseDefinition(definition), { runtimeAssets: { photo: asset() } }),
  ).rejects.toThrow("both static and runtime");
});

test("generated bundles relocate, verify hashes and detect image-only staleness", async () =>
  temporary(async (dir) => {
    const sourceDir = join(dir, "source");
    await mkdir(join(sourceDir, "images"), { recursive: true });
    await writeFile(join(sourceDir, "images", "é space.png"), png());
    const def = parseDefinition(definition, { filename: join(sourceDir, "source.toml") });
    const output = join(dir, "build", "custom.generated.ts");
    const generated = await generateFile(def, output);
    expect(generated).not.toContain(sourceDir);
    expect(() => generate(definition)).toThrow("filesystem-aware");
    const assets = await loadAssets(def);
    const manifest = assetManifest(assets);
    await generateFile(def, output, { check: true });
    const changed = pixels();
    changed.data[0] = 123;
    await writeFile(join(sourceDir, "images", "é space.png"), PNG.sync.write(changed));
    await expect(generateFile(def, output, { check: true })).rejects.toThrow(
      "missing generated asset",
    );
    const moved = join(dir, "moved");
    await mkdir(moved);
    await cp(bundleDirectory(output), join(moved, "custom.generated.assets"), { recursive: true });
    await rm(sourceDir, { recursive: true });
    const loaded = await loadPackagedAssets(
      pathToFileURL(join(moved, "custom.generated.js")).href,
      "custom.generated.assets",
      manifest,
    );
    expect(loaded["<asset:photo>"]).toEqual(assets["<asset:photo>"]);
    const entry = manifest.assets.photo!;
    await writeFile(join(moved, "custom.generated.assets", entry.path), "corrupt");
    await expect(
      loadPackagedAssets(
        pathToFileURL(join(moved, "custom.generated.js")).href,
        "custom.generated.assets",
        manifest,
      ),
    ).rejects.toThrow("hash mismatch");
    expect(
      createHash("sha256")
        .update(Buffer.from(assets["<asset:photo>"]!.data_base64, "base64"))
        .digest("hex"),
    ).toBe(entry.sha256);
  }));

test("patterns preserve supplied assets", async () => {
  const assets = { photo: asset() };
  const seen: unknown[] = [];
  const client = {
    async systemOne(request: { state: unknown; questions: Questions; assets?: unknown }) {
      seen.push(request.assets);
      return {
        model: "x",
        answers: Object.fromEntries(
          Object.keys(request.questions).map((id) => [
            id,
            id === "step"
              ? { type: "choice", choice: "a", confidence: 1, probabilities: { a: 1 } }
              : box,
          ]),
        ),
        usage: { input_tokens: 0, output_tokens: 0 },
      } as SystemOneResult<Questions>;
    },
  };
  await runMany(client, { states: ["x"], questions, assets });
  await runMany(client, { items: [{ state: "x", questions, assets }] });
  await walkTaxonomy(client, { state: "x", tree: { a: "a" }, assets });
  expect(seen).toEqual([assets, assets, assets]);
});

test("vision cache preserves a complete mixed request on every miss and rejects damaged records", async () =>
  temporary(async (dir) => {
    const counts: number[] = [];
    const cache = createCachingFetch({
      dir,
      fetch: async (_, init) => {
        const sent = JSON.parse(String(init?.body));
        counts.push(Object.keys(sent.questions).length);
        return Response.json({
          model: "x",
          answers: { target: box, present: { type: "noul", noul: 0.9 } },
          usage: { input_tokens: 1, output_tokens: 0 },
        });
      },
    });
    const client = new TypeSafeClient({ apiKey: "test", headers, fetch: cache });
    const all = { ...questions, present: { type: "noul", instructions: "Visible?" } } as const;
    const request = { state: "x", questions: all, assets: { photo: asset() } };
    await client.systemOne(request);
    await client.systemOne({
      ...request,
      questions: { ...all, present: { type: "noul", instructions: "Changed" } },
    });
    expect(counts).toEqual([2, 2]);
    const descriptor = {
      version: 1,
      endpoint: "https://api.typesafe.ai/v1/systemone",
      provider: "typesafe",
      model: "jev-latest",
      state: request.state,
      questions: request.questions,
      assets: request.assets,
    };
    const key = createHash("sha256").update(canonicalJson(descriptor)).digest("hex");
    const path = join(dir, "images", "v1", key.slice(0, 2), `${key}.json`);
    const record = JSON.parse(await readFile(path, "utf8"));
    expect(await readFile(path, "utf8")).toBe(`${canonicalJson(record)}\n`);
    record.answers.target.box.top = 1;
    await writeFile(path, JSON.stringify(record));
    await client.systemOne(request);
    expect(counts).toEqual([2, 2, 2]);
  }));

test("CLI preflights all eval cases and rejects Box scalar labels before credentials or calls", async () =>
  temporary(async (dir) => {
    const toml = join(dir, "vision.toml");
    await writeFile(
      toml,
      '[assets.photo]\nruntime=true\n[questions.target]\ntype="box"\ninstructions="<asset:photo>"\n',
    );
    const cases = join(dir, "cases.jsonl");
    const invoke = (...args: string[]) =>
      Bun.spawnSync([process.execPath, "src/cli/index.ts", ...args], {
        cwd: `${import.meta.dir}/..`,
        env: {
          ...process.env,
          TYPESAFE_API_KEY: "",
          CLOUDFLARE_ACCOUNT_ID: "",
          TYPESAFE_BASE_URL: "",
        },
      });
    await writeFile(
      cases,
      `${JSON.stringify({ state: "x", assets: { photo: asset() }, labels: { target: 0 } })}\n`,
    );
    const unsupported = invoke("eval", toml, "--cases", cases, "--experimental-images");
    expect(unsupported.exitCode).toBe(1);
    expect(unsupported.stderr.toString()).toContain("Box scalar labels are unsupported");
    await writeFile(
      cases,
      [
        JSON.stringify({ state: "x", assets: { photo: asset() } }),
        JSON.stringify({ state: "x", assets: { photo: { ...asset(), data_base64: "invalid" } } }),
      ].join("\n"),
    );
    const malformed = invoke("eval", toml, "--cases", cases, "--experimental-images");
    expect(malformed.exitCode).toBe(1);
    expect(malformed.stderr.toString()).toContain("base64");
    expect(malformed.stderr.toString()).not.toContain("API_KEY");
  }));

test("CLI generation detects changed images and missing bundles with no TOML edits", async () =>
  temporary(async (dir) => {
    await mkdir(join(dir, "images"));
    await writeFile(join(dir, "images", "é space.png"), png());
    const toml = join(dir, "source.toml");
    await writeFile(toml, definition);
    const invoke = (...args: string[]) =>
      Bun.spawnSync([process.execPath, "src/cli/index.ts", ...args], {
        cwd: `${import.meta.dir}/..`,
      });
    expect(invoke("generate", toml).exitCode).toBe(0);
    expect(invoke("generate", toml, "--check").exitCode).toBe(0);
    const changed = pixels();
    changed.data[1] = 111;
    await writeFile(join(dir, "images", "é space.png"), PNG.sync.write(changed));
    expect(invoke("generate", toml, "--check").exitCode).toBe(1);
    expect(invoke("generate", toml).exitCode).toBe(0);
    await rm(join(dir, "source.generated.assets"), { recursive: true });
    expect(invoke("generate", toml, "--check").exitCode).toBe(1);
  }));
