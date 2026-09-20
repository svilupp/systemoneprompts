import { expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { root, tsc } from "./helpers.ts";

test("bun can import built output", async () => {
  const build = tsc(["-p", "tsconfig.build.json"]);
  if (build.exitCode !== 0) throw new Error(build.output);

  const dir = await mkdtemp(join(tmpdir(), "jev-bun-"));
  await writeFile(
    join(dir, "package.json"),
    JSON.stringify({
      name: "jev-bun-import",
      private: true,
      type: "module",
      dependencies: { systemoneprompts: `file:${root}` },
    }),
  );
  await writeFile(
    join(dir, "run.mjs"),
    `import { parseDefinition, createFactorEvaluator } from "systemoneprompts";
import { createCachingFetch } from "systemoneprompts/dev";
import { runMany } from "systemoneprompts/patterns";
const def = parseDefinition(\`[questions.ok]\\ntype = "noul"\\ninstructions = "ok?"\\n[factors]\\nyes = { all = ["ok"] }\`);
if (def.questions.ok.type !== "noul") process.exit(2);
const factors = createFactorEvaluator(def.factorDefinitions)({ ok: { type: "noul", noul: 0.9 } });
if (factors.yes !== true) process.exit(3);
if (typeof createCachingFetch !== "function" || typeof runMany !== "function") process.exit(4);
console.log("ok");
`,
  );
  const install = spawnSync("bun", ["install", "--ignore-scripts"], { cwd: dir, encoding: "utf8" });
  if (install.status !== 0) throw new Error(install.stdout + install.stderr);
  const run = spawnSync("bun", ["run.mjs"], { cwd: dir, encoding: "utf8" });
  expect(run.stderr).toBe("");
  expect(run.status).toBe(0);
  expect(run.stdout).toContain("ok");
});
