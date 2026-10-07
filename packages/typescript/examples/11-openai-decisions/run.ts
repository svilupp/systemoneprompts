import { readFile } from "node:fs/promises";
import { OpenAIDecisionsClient } from "systemoneprompts";
import { assertState, evaluateFactors, questions } from "./ticket.generated.js";

const state = JSON.parse(await readFile(new URL("./state.json", import.meta.url), "utf8"));
assertState(state);
const result = await new OpenAIDecisionsClient().systemOne({ state, questions });
console.log({ ...result, factors: evaluateFactors(result.answers) });
