#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const temp = await mkdtemp(join(tmpdir(), "systemoneprompts-package-"));
const packDir = join(temp, "pack");
const consumer = join(temp, "consumer");
const env = { ...process.env, TYPESAFE_API_KEY: "" };

function run(command, args, cwd = packageRoot) {
  const result = spawnSync(command, args, { cwd, env, encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(
      `${command} ${args.join(" ")} failed\n${result.stdout ?? ""}${result.stderr ?? ""}`,
    );
  }
  return result.stdout;
}

try {
  run("bun", ["run", "build"]);
  await mkdir(packDir, { recursive: true });
  await mkdir(consumer, { recursive: true });
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
  const tarball = join(packDir, records[0].filename);

  run("npm", ["init", "-y", "--silent"], consumer);
  run("npm", ["install", "--ignore-scripts", "--silent", tarball], consumer);
  const smoke = `
import { parseDefinition, createFactorEvaluator, TypeSafeClient } from "systemoneprompts";
import { createCachingFetch } from "systemoneprompts/dev";
import { runMany } from "systemoneprompts/patterns";
const def = parseDefinition('[questions.ok]\\ntype = "noul"\\ninstructions = "ok?"\\n[factors]\\nyes = { all = ["ok"] }');
if (def.questions.ok.type !== "noul") throw new Error("root export failed");
if (typeof TypeSafeClient !== "function") throw new Error("TypeSafeClient export failed");
if (!createCachingFetch || !runMany) throw new Error("subpath export failed");
if (!createFactorEvaluator(def.factorDefinitions)({ ok: { type: "noul", noul: 0.9 } }).yes) throw new Error("evaluator failed");
console.log("installed consumer: ok");
`;
  const script = join(consumer, "smoke.mjs");
  await writeFile(script, smoke);
  run("node", [script], consumer);
  run("node_modules/.bin/systemoneprompts", ["--help"], consumer);
  const packageJson = JSON.parse(await readFile(join(packageRoot, "package.json"), "utf8"));
  if (records[0].name !== packageJson.name || records[0].version !== packageJson.version) {
    throw new Error("packed metadata does not match package.json");
  }
  console.log(`Package smoke: ${records[0].filename}`);
} finally {
  await rm(temp, { recursive: true, force: true });
}
