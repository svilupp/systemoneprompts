#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { access, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const artifactIndex = process.argv.indexOf("--artifact");
const artifactArg = artifactIndex >= 0 ? process.argv[artifactIndex + 1] : undefined;
const execute = process.argv.includes("--execute");
if (!artifactArg) {
  console.error(
    "Usage: bun run release:publish -- --artifact <systemoneprompts-*.tgz> [--execute]",
  );
  process.exit(2);
}

const artifact = resolve(packageRoot, artifactArg);
await access(artifact);
const packageJson = JSON.parse(await readFile(join(packageRoot, "package.json"), "utf8"));
if (!artifact.endsWith(`${packageJson.name}-${packageJson.version}.tgz`)) {
  throw new Error(`artifact filename must end with ${packageJson.name}-${packageJson.version}.tgz`);
}

const args = ["publish", artifact, "--access", "public", "--provenance"];
if (!execute) {
  console.log(`Dry run: npm ${args.join(" ")}`);
  console.log("Pass --execute only from the reviewed release workflow.");
  process.exit(0);
}

const result = spawnSync("npm", args, { cwd: packageRoot, stdio: "inherit" });
process.exit(result.status ?? 1);
