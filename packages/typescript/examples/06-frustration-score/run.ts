import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { TypeSafeClient } from "systemoneprompts";
import { assertState, evaluateFactors, model, questions } from "./score.generated.ts";

const root = dirname(fileURLToPath(import.meta.url));
const state = JSON.parse(await readFile(join(root, "states/angry.json"), "utf8"));
assertState(state);

const client = new TypeSafeClient();
const response = await client.systemOne({ state, questions, model });
console.log({
  score: response.answers.frustration.score,
  legend: response.answers.frustration.legend,
  factors: evaluateFactors(response.answers),
});
