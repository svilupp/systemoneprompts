import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { TypeSafeClient } from "systemoneprompts";
import { assertState, evaluateFactors, model, questions } from "./triage.generated.ts";

const root = dirname(fileURLToPath(import.meta.url));
const state = JSON.parse(await readFile(join(root, "states/ticket.json"), "utf8"));
assertState(state);

const client = new TypeSafeClient();
const response = await client.systemOne({ state, questions, model });
const answers = response.answers;
const factors = evaluateFactors(answers);

const spamRisk =
  0.45 * answers.requests_credentials.noul +
  0.3 * answers.sender_identity_mismatch.noul +
  0.25 * answers.unexpected_reward.noul;

let action = "account";
if (factors["spam.corroborated"] || spamRisk >= 0.6) action = "quarantine";
else if (!factors["topic.confident"] || (spamRisk > 0.4 && spamRisk < 0.6)) action = "human_review";
else if (factors["topic.billing"]) action = "billing";
else if (factors["topic.orders"]) action = "orders";

console.log({
  model: response.model,
  topic: answers.topic.choice,
  spamRisk,
  factors,
  action,
  usage: response.usage,
});
