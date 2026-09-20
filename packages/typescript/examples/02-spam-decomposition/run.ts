import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { TypeSafeClient } from "systemoneprompts";
import { assertState, evaluateFactors, model, questions } from "./spam.generated.ts";

const root = dirname(fileURLToPath(import.meta.url));
const state = JSON.parse(await readFile(join(root, "states/phish.json"), "utf8"));
assertState(state);

const client = new TypeSafeClient();
const response = await client.systemOne({ state, questions, model });
const factors = evaluateFactors(response.answers);
const answers = response.answers;
const spamRisk =
  0.45 * answers.requests_credentials.noul +
  0.3 * answers.sender_identity_mismatch.noul +
  0.25 * answers.unexpected_reward.noul;
console.log({
  broad: answers.broad_spam.noul,
  decomposed: {
    requests_credentials: answers.requests_credentials.noul,
    sender_identity_mismatch: answers.sender_identity_mismatch.noul,
    unexpected_reward: answers.unexpected_reward.noul,
  },
  factors,
  spamRisk,
});
