#!/usr/bin/env node
import { parseArgs } from "node:util";
import { runCache } from "./cache.js";
import { runCheck } from "./check.js";
import { runEval } from "./eval.js";
import { runGenerate } from "./generate.js";
import { fail } from "./io.js";
import { runRun } from "./run.js";

const USAGE = `systemoneprompts <command> [options]

Commands:
  check     <files...> [--strict]
  generate  <files...> [--out dir] [--check]
  run       <file> --state s.json | <stdin> [--cache] [--json] [--model name]
  eval      <file> --cases cases.jsonl [--cache] [--sweep factor] [--report out.json] [--model name]
  cache     stats | clear
`;

async function main(): Promise<void> {
  const { values, positionals } = parseArgs({
    args: process.argv.slice(2),
    allowPositionals: true,
    options: {
      strict: { type: "boolean", default: false },
      out: { type: "string" },
      check: { type: "boolean", default: false },
      state: { type: "string" },
      cache: { type: "boolean", default: false },
      json: { type: "boolean", default: false },
      cases: { type: "string" },
      sweep: { type: "string" },
      report: { type: "string" },
      model: { type: "string" },
      help: { type: "boolean", default: false },
    },
  });

  if (values.help || positionals.length === 0) {
    console.log(USAGE);
    process.exit(values.help ? 0 : 1);
  }

  const [command, ...rest] = positionals;
  switch (command) {
    case "check":
      await runCheck(rest, Boolean(values.strict));
      break;
    case "generate":
      await runGenerate(rest, { out: values.out, check: Boolean(values.check) });
      break;
    case "run":
      await runRun(rest[0], {
        state: values.state,
        cache: Boolean(values.cache),
        json: Boolean(values.json),
        model: values.model,
      });
      break;
    case "eval":
      await runEval(rest[0], {
        cases: values.cases,
        cache: Boolean(values.cache),
        sweep: values.sweep,
        report: values.report,
        model: values.model,
      });
      break;
    case "cache":
      await runCache(rest[0]);
      break;
    default:
      fail(`unknown command \`${command}\`\n\n${USAGE}`);
  }
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
