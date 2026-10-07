#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const temp = await mkdtemp(join(tmpdir(), "systemoneprompts-package-"));
const packDir = join(temp, "pack");
const env = { ...process.env, TYPESAFE_API_KEY: "" };

const SMOKE = `
import { realpathSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, sep, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseDefinition, createFactorEvaluator, TypeSafeClient, OpenAIDecisionsClient } from "systemoneprompts";
import { createCachingFetch, createCachedOpenAIDecisionsClient } from "systemoneprompts/dev";
import { runMany } from "systemoneprompts/patterns";
const def = parseDefinition('[questions.ok]\\ntype = "noul"\\ninstructions = "ok?"\\n[factors]\\nyes = { all = ["ok"] }');
if (def.questions.ok.type !== "noul") throw new Error("root export failed");
if (typeof TypeSafeClient !== "function") throw new Error("TypeSafeClient export failed");
if (!createCachingFetch || !runMany) throw new Error("subpath export failed");
if (!createFactorEvaluator(def.factorDefinitions)({ ok: { type: "noul", noul: 0.9 } }).yes) {
  throw new Error("evaluator failed");
}
const resolved = realpathSync(fileURLToPath(import.meta.resolve("systemoneprompts")));
const consumerRoot = realpathSync(dirname(fileURLToPath(import.meta.url)));
if (resolved !== consumerRoot && !resolved.startsWith(consumerRoot + sep)) {
  throw new Error(\`import resolved outside consumer: \${resolved}\`);
}
for (const Client of [TypeSafeClient, OpenAIDecisionsClient]) {
  const client = new Client({ apiKey: "consumer-test", fetch: async (url) => {
    const openai = Client === OpenAIDecisionsClient;
    if (!url.endsWith(openai ? "/v1/decisions" : "/v1/systemone")) throw new Error("wrong provider route");
    return Response.json({ model: "mock", usage: { input_tokens: 1, output_tokens: 0 }, answers: openai
      ? [{ name: "q0", type: "predicate", probability: 0.9 }]
      : { ok: { type: "noul", noul: 0.9 } } });
  } });
  const result = await client.systemOne({ state: "ok", questions: def.questions });
  if (!createFactorEvaluator(def.factorDefinitions)(result.answers).yes) throw new Error("provider normalization failed");
}
const cacheRoot = mkdtempSync(join(tmpdir(), "openai-consumer-cache-"));
try {
  let calls = 0;
  const raw = new OpenAIDecisionsClient({ apiKey: "consumer-test", fetch: async () => {
    calls++;
    return Response.json({ model: "mock", usage: { input_tokens: 1, output_tokens: 0 }, answers: [{ name: "q0", type: "predicate", probability: 0.9 }] });
  } });
  const cached = createCachedOpenAIDecisionsClient({ client: raw, dir: cacheRoot });
  const request = { state: "ok", questions: def.questions };
  await cached.client.systemOne(request);
  const hit = await cached.client.systemOne(request);
  if (calls !== 1 || hit.usage.input_tokens !== 0) throw new Error("packed cache factory failed");
} finally { rmSync(cacheRoot, { recursive: true, force: true }); }
console.log("installed consumer: ok");
`;

function run(command, args, cwd = packageRoot) {
  const result = spawnSync(command, args, { cwd, env, encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(
      `${command} ${args.join(" ")} failed\n${result.stdout ?? ""}${result.stderr ?? ""}`,
    );
  }
  return result.stdout;
}

function exportTargets(exports) {
  const targets = [];
  for (const conditions of Object.values(exports)) {
    if (typeof conditions === "string") targets.push(conditions);
    else {
      for (const target of Object.values(conditions)) {
        if (typeof target === "string") targets.push(target);
      }
    }
  }
  return [...new Set(targets)];
}

function packPaths(record) {
  if (!Array.isArray(record.files)) throw new Error("npm pack json missing files");
  return new Set(record.files.map((file) => String(file.path).replaceAll("\\", "/")));
}

async function writeConsumer(directory) {
  await mkdir(directory, { recursive: true });
  await writeFile(
    join(directory, "package.json"),
    `${JSON.stringify({ name: "systemoneprompts-smoke", private: true, type: "module" }, null, 2)}\n`,
  );
  await writeFile(join(directory, "smoke.mjs"), SMOKE);
  await writeFile(
    join(directory, "ok.toml"),
    '[questions.ok]\ntype = "noul"\ninstructions = "ok?"\n',
  );
  return {
    cwd: directory,
    script: join(directory, "smoke.mjs"),
    cli: join(directory, "node_modules", "systemoneprompts", "dist", "cli", "index.js"),
    bin: join(directory, "node_modules", ".bin", "systemoneprompts"),
  };
}

function smokeInstalled(label, consumer) {
  const { script, cli, bin } = consumer;
  run("node", [script], consumer.cwd);
  run("bun", [script], consumer.cwd);
  run(bin, ["--help"], consumer.cwd);
  run("node", [cli, "check", "ok.toml"], consumer.cwd);
  run("bun", [cli, "check", "ok.toml"], consumer.cwd);
  console.error(`${label}: Node and Bun consumers OK`);
}

try {
  run("bun", ["run", "build"]);
  const packageJson = JSON.parse(await readFile(join(packageRoot, "package.json"), "utf8"));
  const cliSource = await readFile(join(packageRoot, "dist", "cli", "index.js"), "utf8");
  if (!cliSource.startsWith("#!/usr/bin/env node\n")) {
    throw new Error("published CLI shebang must be #!/usr/bin/env node for npm/npx and bunx");
  }

  await mkdir(packDir, { recursive: true });
  const packJson = run("npm", [
    "pack",
    "--ignore-scripts",
    "--json",
    "--pack-destination",
    packDir,
  ]);
  const records = JSON.parse(packJson);
  if (!Array.isArray(records) || records.length !== 1 || typeof records[0]?.filename !== "string") {
    throw new Error(`unexpected npm pack output: ${packJson}`);
  }
  const record = records[0];
  const tarball = join(packDir, record.filename);
  if (record.name !== packageJson.name || record.version !== packageJson.version) {
    throw new Error("packed metadata does not match package.json");
  }

  const packed = packPaths(record);
  const required = new Set(
    exportTargets(packageJson.exports)
      .concat(Object.values(packageJson.bin ?? {}))
      .map((target) => target.replace(/^\.\//, "")),
  );
  const missing = [...required].filter((path) => !packed.has(path));
  if (missing.length) throw new Error(`packed tarball missing: ${missing.join(", ")}`);
  const leaked = [...packed].filter(
    (path) => path.startsWith("src/") || path.startsWith("tests/") || path.startsWith("scripts/"),
  );
  if (leaked.length)
    throw new Error(`packed tarball leaked development paths: ${leaked.join(", ")}`);

  const npmConsumer = await writeConsumer(join(temp, "npm-consumer"));
  const bunConsumer = await writeConsumer(join(temp, "bun-consumer"));

  run("npm", ["install", "--ignore-scripts", "--silent", tarball], npmConsumer.cwd);
  smokeInstalled("npm pack + npm install", npmConsumer);

  run("bun", ["add", "--ignore-scripts", tarball], bunConsumer.cwd);
  smokeInstalled("npm pack + bun add", bunConsumer);

  console.log(`Package smoke: ${record.filename} (Node and Bun)`);
} finally {
  await rm(temp, { recursive: true, force: true });
}
