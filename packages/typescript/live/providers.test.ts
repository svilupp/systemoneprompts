import { expect, test } from "bun:test";
import fixture from "../conformance/v1/providers/native-decisions.json" with { type: "json" };
import { loadDotEnv } from "../src/cli/env.js";
import { probe } from "./provider-probe.js";

loadDotEnv();
for (const [provider, model, key] of [
  ["typesafe", "jev-latest", "TYPESAFE_API_KEY"],
  ["openai", "gpt-6-luna", "OPENAI_API_KEY"],
  ["openrouter", "~typesafe/jev-latest", "OPENROUTER_API_KEY"],
  ["openrouter", "openai/gpt-6-luna-decisions", "OPENROUTER_API_KEY"],
  ["cloudflare", "clef", "CLOUDFLARE_API_TOKEN"],
  ["cloudflare", "clef-flash", "CLOUDFLARE_API_TOKEN"],
]) {
  const enabled =
    process.env[key!] && (provider !== "cloudflare" || process.env.CLOUDFLARE_ACCOUNT_ID);
  (enabled ? test : test.skip)(
    `${provider}/${model}: native answers and cache hit`,
    async () => {
      const saved = process.env.CLOUDFLARE_ACCOUNT_ID;
      if (provider === "typesafe") delete process.env.CLOUDFLARE_ACCOUNT_ID;
      try {
        const result = await probe({
          provider,
          model,
          key,
          mode: "environment",
          state: fixture.state,
          questions: fixture.questions,
        });
        expect(result.status).toBe("pass");
        expect(result.networkCalls).toBe(1);
      } finally {
        if (saved !== undefined) process.env.CLOUDFLARE_ACCOUNT_ID = saved;
      }
    },
    30_000,
  );
}
