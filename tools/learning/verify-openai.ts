import { readFileSync } from "node:fs";
import { partitionAnswers } from "../../packages/typescript/src/answers.js";
import { createFactorEvaluator } from "../../packages/typescript/src/factors/evaluate.js";

const report = JSON.parse(
	readFileSync(
		new URL("./openai-decisions-results.json", import.meta.url),
		"utf8",
	),
);
const result = report.cases.find(
	(c: { name: string }) => c.name === "translated_mixed",
).normalized;
const questions = JSON.parse(
	'{"charged.twice":{"type":"noul"},"__proto__":{"type":"choice","criteria":{"billing":"Payments and refunds","shipping":"Delivery and tracking"}},"severity":{"type":"score","criteria":["No issue",{"issue":"Payment requires correction"},"Permanent account loss"]}}',
);
const partition = partitionAnswers(questions, result.answers);
if (partition.missing.length || partition.malformed.length)
	throw new Error(JSON.stringify(partition));
const factors = createFactorEvaluator({
	billing: { ref: "__proto__", choice: "billing" },
	charge: { ref: "charged.twice", noul: { gte: 0.5 } },
	severity_band: { ref: "severity", score: { gte: 0.5, lte: 1.5 } },
})(result.answers);
if (!Object.values(factors).every(Boolean))
	throw new Error(JSON.stringify(factors));
console.log(
	"TypeScript: recorded normalized answers pass partitionAnswers and all three factor predicates",
);
