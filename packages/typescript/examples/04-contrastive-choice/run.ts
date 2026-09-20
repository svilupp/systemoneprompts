import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { TypeSafeClient } from "systemoneprompts";
import { assertState, evaluateFactors, model, questions } from "./choice.generated.ts";

const root = dirname(fileURLToPath(import.meta.url));
const state = JSON.parse(await readFile(join(root, "states/policy.json"), "utf8"));
assertState(state);

const client = new TypeSafeClient();
const response = await client.systemOne({ state, questions, model });
console.log({ answers: response.answers, factors: evaluateFactors(response.answers) });
