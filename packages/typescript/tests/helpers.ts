import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const root = join(dirname(fileURLToPath(import.meta.url)), "..");

export function fixture(...parts: string[]): string {
  return readFileSync(join(root, "tests", "fixtures", ...parts), "utf8");
}

export function fixturePath(...parts: string[]): string {
  return join(root, "tests", "fixtures", ...parts);
}

/** Run the repo's own `tsc` (no `npx` network lookups). */
export function tsc(args: string[]): { exitCode: number; output: string } {
  const result = spawnSync(join(root, "node_modules", ".bin", "tsc"), args, {
    cwd: root,
    encoding: "utf8",
  });
  return { exitCode: result.status ?? 1, output: `${result.stdout}${result.stderr}` };
}

/** Run the CLI from source. `env` is layered over the current environment. */
export function cli(
  args: string[],
  opts: { cwd?: string; input?: string; env?: Record<string, string> } = {},
): { exitCode: number; stdout: string; stderr: string } {
  const result = spawnSync("bun", [join(root, "src", "cli", "index.ts"), ...args], {
    cwd: opts.cwd ?? root,
    encoding: "utf8",
    input: opts.input,
    env: { ...process.env, ...opts.env },
  });
  return { exitCode: result.status ?? 1, stdout: result.stdout, stderr: result.stderr };
}
