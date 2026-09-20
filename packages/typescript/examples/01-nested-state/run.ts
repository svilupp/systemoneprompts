import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { TypeSafeClient } from "systemoneprompts";
import { assertState, evaluateFactors, model, questions } from "./nested-state.generated.ts";

const root = dirname(fileURLToPath(import.meta.url));
const state = JSON.parse(await readFile(join(root, "states/ticket.json"), "utf8"));
assertState(state);

const client = new TypeSafeClient();
const response = await client.systemOne({ state, questions, model });
const factors = evaluateFactors(response.answers);
console.log({ model: response.model, answers: response.answers, factors, usage: response.usage });
