import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { TypeSafeClient } from "systemoneprompts";
import { assertState, evaluateFactors, model, questions } from "./routing.generated.ts";

const root = dirname(fileURLToPath(import.meta.url));
const state = JSON.parse(await readFile(join(root, "states/ticket.json"), "utf8"));
assertState(state);

const client = new TypeSafeClient();
const response = await client.systemOne({ state, questions, model });
const factors = evaluateFactors(response.answers);
const topic = response.answers.topic;

let action = "route";
if (!factors["topic.confident"]) action = "human_review";
else if (factors["refund.gray"]) action = "ask_clarifying_question";
else if (topic.choice === "billing") action = "billing_queue";

console.log({ topic: topic.choice, confidence: topic.confidence, factors, action });
