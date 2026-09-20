import { spawn, spawnSync } from "node:child_process";
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
): Promise<{ exitCode: number; stdout: string; stderr: string }> {
  const env = {
    ...process.env,
    TYPESAFE_BASE_URL: "",
    CLOUDFLARE_ACCOUNT_ID: "",
    CLOUDFLARE_API_TOKEN: "",
    ...opts.env,
  };
  return new Promise((resolve) => {
    const child = spawn("bun", [join(root, "src", "cli", "index.ts"), ...args], {
      cwd: opts.cwd ?? root,
      env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });
    child.once("error", (error) => {
      stderr += `${error.message}\n`;
    });
    child.once("close", (code) => {
      resolve({ exitCode: code ?? 1, stdout, stderr });
    });
    child.stdin.end(opts.input ?? "");
  });
}
