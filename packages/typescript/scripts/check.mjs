#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptsDir = dirname(fileURLToPath(import.meta.url));
const packageRoot = dirname(scriptsDir);
const runQuiet = join(scriptsDir, "run-quiet.sh");
const toolBin = join(packageRoot, "node_modules", ".bin");
const env = { ...process.env, PATH: `${toolBin}:${process.env.PATH ?? ""}` };

const legs = [
  ["Typecheck", ["bun", "run", "typecheck"]],
  ["Lint", ["bun", "run", "lint"]],
  ["Tests", ["bun", "run", "test:unit"]],
  ["Fitness tests", ["bun", "run", "test:fitness"]],
  ["Conformance tests", ["bun", "run", "test:conformance"]],
  ["Generated examples", ["bun", "run", "examples:check"]],
  ["Public API", ["bun", "run", "api:check"]],
];

const requested = process.argv.slice(2);
const selected = requested.length ? legs.filter(([name]) => requested.includes(name)) : legs;

if (requested.length && selected.length !== requested.length) {
  const known = legs.map(([name]) => name).join(", ");
  const unknown = requested.filter((name) => !legs.some(([knownName]) => knownName === name));
  console.error(`unknown check leg(s): ${unknown.join(", ")}; known: ${known}`);
  process.exit(2);
}

let failed = false;
for (const [label, command] of selected) {
  const result = spawnSync("sh", [runQuiet, label, "--", ...command], {
    cwd: packageRoot,
    env,
    stdio: "inherit",
  });
  if (result.error) {
    console.error(`${label}: unable to start: ${result.error.message}`);
    failed = true;
  } else if (result.status !== 0) {
    failed = true;
  }
}

process.exit(failed ? 1 : 0);
