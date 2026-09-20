#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { chmod, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptsDir = dirname(fileURLToPath(import.meta.url));
const packageRoot = dirname(scriptsDir);
const dist = join(packageRoot, "dist");
const tsc = join(
  packageRoot,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "tsc.cmd" : "tsc",
);

await rm(dist, { recursive: true, force: true });
const result = spawnSync(tsc, ["-p", join(packageRoot, "tsconfig.build.json")], {
  cwd: packageRoot,
  stdio: "inherit",
});
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);

await chmod(join(dist, "cli", "index.js"), 0o755);
console.error("Build: OK");
