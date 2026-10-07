#!/usr/bin/env node

import { access, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const required = [
  "src/index.ts",
  "src/dev/index.ts",
  "src/patterns/index.ts",
  "src/cli/index.ts",
  "README.md",
  "LICENSE",
];
for (const relative of required) await access(join(packageRoot, relative));

const source = await readFile(join(packageRoot, "src/index.ts"), "utf8");
for (const name of [
  "parseDefinition",
  "checkDefinition",
  "createStateAssert",
  "createFactorEvaluator",
  "generate",
  "TypeSafeClient",
  "OpenAIDecisionsClient",
  "OpenAIDecisionsError",
  "CloudflareDecisionsClient",
  "CloudflareDecisionsError",
]) {
  if (!source.includes(name)) throw new Error(`public API is missing ${name}`);
}
console.log(`Public API: ${required.length} package surfaces present`);
