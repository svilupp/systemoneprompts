import { expect, test } from "bun:test";
import { join } from "node:path";
import { loadDotEnv } from "../src/cli/env.ts";
import { parseDefinition, resolveModel, TypeSafeClient } from "../src/index.ts";
import { fixture } from "../tests/helpers.ts";

loadDotEnv();

const gated = process.env.TYPESAFE_API_KEY ? test : test.skip;

gated("example 07 shapes against the live API", async () => {
  const def = parseDefinition(fixture("golden/triage.toml"));
  const model = resolveModel(def.model);
  const client = new TypeSafeClient({ defaultModel: model });
  const response = await client.systemOne({
    state: {
      ticket: {
        message: "I was charged twice for order A-104. Please refund the duplicate.",
        sender: { email: "sam@example.com", display_name: "Sam" },
      },
      customer: { open_orders: [{ id: "A-104" }] },
      policy: { sensitive_credentials: ["password", "API key"] },
    },
    questions: def.questions,
    model,
  });
  expect(typeof response.model).toBe("string");
  expect(response.answers.topic?.type).toBe("choice");
  expect(typeof (response.answers.topic as { choice: string }).choice).toBe("string");
  expect(response.answers["spam.requests_credentials"]?.type).toBe("noul");
  expect(typeof (response.answers["spam.requests_credentials"] as { noul: number }).noul).toBe(
    "number",
  );
  expect(response.answers.frustration?.type).toBe("score");
  expect(typeof (response.answers.frustration as { score: number }).score).toBe("number");
  expect(response.answers.frustration).toHaveProperty("legend");
});

gated("CLI --model overrides the TOML pin on a live call", async () => {
  const root = join(import.meta.dir, "..");
  const run = Bun.spawnSync({
    cmd: [
      "bun",
      "src/cli/index.ts",
      "run",
      "examples/01-nested-state/nested-state.toml",
      "--state",
      "examples/01-nested-state/states/ticket.json",
      "--json",
      "--model",
      "jev-1.13.0",
    ],
    cwd: root,
    stdout: "pipe",
    stderr: "pipe",
    env: { ...process.env },
  });
  if (run.exitCode !== 0) {
    throw new Error(run.stdout.toString() + run.stderr.toString());
  }
  const body = JSON.parse(run.stdout.toString()) as { model: string };
  expect(body.model).toBe("jev-1.13.0");
});
