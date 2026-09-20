#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const result = spawnSync("npm", ["publish", "--access", "public", "--provenance"], {
  cwd: packageRoot,
  stdio: "inherit",
});
process.exit(result.status ?? 1);
