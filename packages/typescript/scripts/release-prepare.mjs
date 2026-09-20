#!/usr/bin/env node

import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const versionIndex = process.argv.indexOf("--version");
const version = versionIndex >= 0 ? process.argv[versionIndex + 1] : undefined;
if (!version || !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(version)) {
  console.error("Usage: bun run release:prepare -- --version <semver>");
  process.exit(2);
}

const packagePath = join(packageRoot, "package.json");
const packageJson = JSON.parse(await readFile(packagePath, "utf8"));
const previous = packageJson.version;
packageJson.version = version;
await writeFile(packagePath, `${JSON.stringify(packageJson, null, 2)}\n`);
console.log(`Prepared ${packageJson.name}: ${previous} -> ${version}`);
console.log(
  "Update the package changelog, run release:check, review the diff, then run release:publish.",
);
