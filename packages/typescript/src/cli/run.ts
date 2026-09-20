import { createFactorEvaluator } from "../factors/evaluate.js";
import { createStateAssert, type StateAssert } from "../state/requirements.js";
import { createClient, fail, loadChecked, parseJson, readStdin, readText } from "./io.js";

export async function runRun(
  file: string | undefined,
  options: { state?: string; cache?: boolean; json?: boolean; model?: string },
): Promise<void> {
  if (!file) {
    fail("systemoneprompts run <file> --state s.json | <stdin> [--cache] [--json] [--model name]");
  }
  const def = await loadChecked(file);

  const stateText = options.state ? await readText(options.state) : await readStdin();
  const state = parseJson(stateText, options.state ?? "<stdin>");
  const assertState: StateAssert = createStateAssert(def.requires);
  assertState(state);

  const { client, model, cache } = createClient(def, options);
  const response = await client.systemOne({
    state,
    questions: def.questions,
    model,
  });
  const factors = createFactorEvaluator(def.factorDefinitions)(response.answers);
  const cacheStats = cache?.stats();

  if (options.json) {
    console.log(
      JSON.stringify(
        {
          model: response.model,
          answers: response.answers,
          factors,
          usage: response.usage,
          cache: cacheStats,
        },
        null,
        2,
      ),
    );
    return;
  }

  console.log(`model  ${response.model}`);
  if (def.meta.title) console.log(`title  ${def.meta.title}`);
  console.log("");
  console.log("answers");
  for (const [id, answer] of Object.entries(response.answers)) {
    console.log(`  ${id}`);
    console.log(`    ${formatAnswer(answer)}`);
  }
  console.log("");
  console.log("factors");
  for (const [id, value] of Object.entries(factors)) {
    console.log(`  ${id}  ${value}`);
  }
  console.log("");
  console.log(`usage  in=${response.usage.input_tokens}  out=${response.usage.output_tokens}`);
  if (cacheStats) {
    console.log(`cache  hits=${cacheStats.hits}  misses=${cacheStats.misses}`);
  }
}

function formatAnswer(answer: unknown): string {
  if (!answer || typeof answer !== "object") return String(answer);
  const a = answer as Record<string, unknown>;
  if (a.type === "noul") return `noul=${a.noul}`;
  if (a.type === "choice") return `choice=${a.choice}  confidence=${a.confidence}`;
  if (a.type === "score") return `score=${a.score}  confidence=${a.confidence}`;
  return JSON.stringify(a);
}
