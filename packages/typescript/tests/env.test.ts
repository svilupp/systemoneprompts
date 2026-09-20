import { afterEach, describe, expect, test } from "bun:test";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadDotEnv } from "../src/cli/env.ts";

describe("loadDotEnv", () => {
  const key = "CLOUDFLARE_ACCOUNT_ID";
  const previous = process.env[key];

  afterEach(() => {
    if (previous === undefined) delete process.env[key];
    else process.env[key] = previous;
  });

  test("does not refill an empty string from .env", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-dotenv-"));
    await writeFile(join(dir, ".env"), `${key}=from-file\n`);
    process.env[key] = "";
    loadDotEnv(dir);
    expect(process.env[key]).toBe("");
  });
});
