#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const runQuiet = join(packageRoot, "scripts", "run-quiet.sh");

function run(label, args) {
  const result = spawnSync("sh", [runQuiet, label, "--", "bun", "run", ...args], {
    cwd: packageRoot,
    stdio: "inherit",
  });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

run("Checks", ["check"]);
run("Package smoke", ["test:package"]);
console.log("Release check: OK");
