import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { TypeSafeClient } from "../src/client.js";
import { checkDefinition } from "../src/definition/check.js";
import { loadDefinition, parseDefinition } from "../src/definition/parse.js";
import { imageAsset, loadAssets, loadPackagedAssets } from "../src/file-assets.js";
import { generateFile } from "../src/generate/generate.js";
import { cli } from "./helpers.js";

const savedEnv: Record<string, string | undefined> = {};
beforeEach(() => {
  for (const key of ["CLOUDFLARE_ACCOUNT_ID", "TYPESAFE_BASE_URL"]) {
    savedEnv[key] = process.env[key];
    delete process.env[key];
  }
});
afterEach(() => {
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

const headers = { "TypeSafe-Danger-Zone-Images": "true" };
const image = await readFile(
  new URL("../../../conformance/v1/images/rectangle.png", import.meta.url),
);
const asset = imageAsset(image);

for (const other of ["photo_reference", "photo2"])
  for (const source of ["static", "runtime"])
    test(`${source} and generated loaders preserve complete managed tokens with ${other}`, async () => {
      const dir = await mkdtemp(join(tmpdir(), "managed-assets-"));
      try {
        await writeFile(join(dir, "photo.png"), image);
        const definition = parseDefinition(
          `[assets.photo]\n${source === "static" ? 'path="photo.png"' : "runtime=true"}\n[assets.${other}]\nruntime=true\n[questions.q]\ntype="noul"\ninstructions="Compare photo prose with <asset:${other}>"`,
          { filename: join(dir, "input.toml") },
        );
        expect(checkDefinition(definition).filter((d) => d.severity === "error")).toEqual([]);
        const runtime = { [other]: asset, ...(source === "runtime" ? { photo: asset } : {}) };
        const direct = await loadAssets(definition, { runtimeAssets: runtime });
        const output = join(dir, "output.generated.ts");
        await generateFile(definition, output);
        const manifest =
          source === "static"
            ? JSON.parse(
                await readFile(join(dir, "output.generated.assets", "manifest.json"), "utf8"),
              )
            : { version: 1, assets: {} };
        expect(Object.keys(manifest.assets)).toEqual(source === "static" ? ["photo"] : []);
        const packaged = await loadPackagedAssets(
          pathToFileURL(output).href,
          "output.generated.assets",
          manifest,
          { runtimeAssets: runtime },
          source === "static" ? [other] : ["photo", other],
        );
        const sent: any[] = [];
        const client = new TypeSafeClient({
          apiKey: "test",
          cloudflareAccountId: "",
          baseURL: "https://api.typesafe.ai",
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
        const state = { photo: "<asset:photo>", text: `photo and ${other} are ordinary prose` };
        for (const assets of [direct, packaged]) {
          await client.systemOne({ state, questions: definition.questions, assets });
          expect(Object.keys(sent.at(-1).assets).sort()).toEqual(
            ["<asset:photo>", `<asset:${other}>`].sort(),
          );
          expect(sent.at(-1).state).toEqual(state);
          expect(sent.at(-1).questions.q.instructions).toBe(
            `Compare photo prose with <asset:${other}>`,
          );
        }
        expect(packaged).toEqual(direct);
        await expect(
          loadAssets(definition, { runtimeAssets: { ...runtime, "<asset:photo>": asset } }),
        ).rejects.toThrow("collid");
        await expect(
          loadPackagedAssets(
            pathToFileURL(output).href,
            "output.generated.assets",
            manifest,
            { runtimeAssets: { ...runtime, "<asset:photo>": asset } },
            source === "static" ? [other] : ["photo", other],
          ),
        ).rejects.toThrow("collid");
      } finally {
        await rm(dir, { recursive: true, force: true });
      }
    });

test("managed helpers preserve undeclared raw native references", async () => {
  const definition = parseDefinition('[assets.photo]\nruntime=true\n[questions.q]\ntype="noul"');
  expect(
    await loadAssets(definition, { runtimeAssets: { photo: asset, "<extra>": asset } }),
  ).toEqual({ "<asset:photo>": asset, "<extra>": asset });
});

test("CLI check/generate/run allow a static image used only in state and reject unused images at request time", async () => {
  const dir = await mkdtemp(join(tmpdir(), "managed-state-"));
  const received: any[] = [];
  const server = createServer(async (request, response) => {
    let body = "";
    for await (const chunk of request) body += chunk;
    received.push(JSON.parse(body));
    response.setHeader("Content-Type", "application/json");
    response.end(
      JSON.stringify({
        model: "jev",
        answers: { q: { type: "noul", noul: 1 } },
        usage: { input_tokens: 1, output_tokens: 1 },
      }),
    );
  });
  try {
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("missing server address");
    await writeFile(join(dir, "photo.png"), image);
    const file = join(dir, "input.toml");
    await writeFile(
      file,
      '[assets.photo]\npath="photo.png"\n[questions.q]\ntype="noul"\ninstructions="Does the photo show a rectangle?"',
    );
    const state = join(dir, "state.json");
    await writeFile(state, JSON.stringify({ image: "<asset:photo>" }));
    for (const command of [
      ["check", file],
      ["generate", file],
      ["generate", "--check", file],
    ]) {
      const result = await cli(command);
      expect(result.stderr).toBe("");
      expect(result.exitCode).toBe(0);
    }
    const args = [
      "run",
      file,
      "--state",
      state,
      "--experimental-images",
      "--base-url",
      `http://127.0.0.1:${address.port}`,
      "--json",
    ];
    const valid = await cli(args, { env: { TYPESAFE_API_KEY: "test" } });
    expect(valid.stderr).toBe("");
    expect(valid.exitCode).toBe(0);
    expect(received[0].assets).toEqual({ "<asset:photo>": asset });
    await writeFile(state, "{}");
    const unused = await cli(args, { env: { TYPESAFE_API_KEY: "test" } });
    expect(unused.exitCode).toBe(1);
    expect(unused.stderr).toContain("unused");
    expect(received).toHaveLength(1);
    await writeFile(join(dir, "photo.png"), "corrupt");
    for (const command of ["check", "generate"])
      expect((await cli([command, file])).exitCode).toBe(1);
    expect((await loadDefinition(file)).assets.photo).toEqual({ path: "photo.png" });
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(dir, { recursive: true, force: true });
  }
});
