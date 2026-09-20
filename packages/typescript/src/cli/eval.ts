import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { Definition } from "../definition/schema.js";
import { type AnswersFor, createFactorEvaluator, NOUL_CUTOFF } from "../factors/evaluate.js";
import { COMPARATOR_KEYS, type ComparatorKey, type FactorTable } from "../factors/schema.js";
import { isJsonValue, isPlainObject } from "../json.js";
import { createStateAssert, type StateAssert } from "../state/requirements.js";
import { createClient, fail, loadChecked, readText } from "./io.js";

/**
 * One line of `cases.jsonl`. `labels` are expected answers keyed by question id
 * (Choice label, Noul Boolean, or Score level); `factors` are expected factor values.
 */
export interface EvalCase {
  id?: string;
  state: unknown;
  labels?: Record<string, unknown>;
  factors?: Record<string, boolean>;
}

interface Prediction {
  id: string;
  answers: AnswersFor<Definition["questions"]>;
  factors: Record<string, boolean>;
  testCase: EvalCase;
}

interface Tally {
  correct: number;
  total: number;
}

interface Sweep {
  id: string;
  ref: string;
  field: "noul" | "score" | "confidence";
  key: ComparatorKey;
  table: FactorTable;
  thresholds: number[];
}

export async function runEval(
  file: string | undefined,
  options: { cases?: string; cache?: boolean; sweep?: string; report?: string; model?: string },
): Promise<void> {
  if (!file || !options.cases) {
    fail(
      "systemoneprompts eval <file> --cases cases.jsonl [--cache] [--sweep factor] [--report out.json] [--model name]",
    );
  }
  if (
    options.report &&
    (resolve(options.report) === resolve(file) ||
      resolve(options.report) === resolve(options.cases))
  ) {
    fail("--report must not overwrite the definition or cases input");
  }
  const def = await loadChecked(file);
  const cases = parseJsonl(await readText(options.cases), options.cases, def);
  const evaluate = createFactorEvaluator(def.factorDefinitions);
  const assertState: StateAssert = createStateAssert(def.requires);

  const stateErrors: string[] = [];
  for (const [index, testCase] of cases.entries()) {
    try {
      assertState(testCase.state);
    } catch (error) {
      const id = testCase.id ?? String(index);
      stateErrors.push(`case ${id}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  if (stateErrors.length > 0) {
    for (const message of stateErrors) console.error(message);
    fail(`${stateErrors.length} invalid eval case(s)`);
  }

  const sweep = options.sweep ? prepareSweep(options.sweep, def) : undefined;
  if (
    sweep &&
    !cases.some(
      (testCase) =>
        groundTruth(sweep.id, sweep.ref, sweep.field, sweep.key, testCase) !== undefined,
    )
  ) {
    fail(`--sweep: no usable truth samples for factor \`${sweep.id}\``);
  }

  const questionStats: Record<
    string,
    Tally & { confusion: Record<string, Record<string, number>> }
  > = Object.create(null);
  const factorStats: Record<string, Tally> = Object.create(null);
  const nearThreshold: Record<string, number> = Object.create(null);
  const predictions: Prediction[] = [];
  let errors = 0;
  const { client, model, cache } = createClient(def, options);
  for (const [index, testCase] of cases.entries()) {
    const id = testCase.id ?? String(index);
    try {
      const response = await client.systemOne({
        state: testCase.state,
        questions: def.questions,
        model,
      });

      for (const [qid, expected] of Object.entries(testCase.labels ?? {})) {
        const answer = response.answers[qid];
        const stats = (questionStats[qid] ??= {
          correct: 0,
          total: 0,
          confusion: Object.create(null),
        });
        stats.total += 1;
        const predicted = labelOf(answer) ?? "<none>";
        const expectedLabel = String(expected);
        if (predicted === expectedLabel) stats.correct += 1;
        const row = (stats.confusion[expectedLabel] ??= Object.create(null));
        row[predicted] = (row[predicted] ?? 0) + 1;
        recordNear(qid, answer, nearThreshold);
      }

      let factors: Record<string, boolean>;
      try {
        factors = evaluate(response.answers);
      } catch (error) {
        errors += 1;
        console.error(
          `case ${id}: factor evaluation failed: ${error instanceof Error ? error.message : String(error)}`,
        );
        continue;
      }
      predictions.push({ id, answers: response.answers, factors, testCase });
      for (const [fid, expected] of Object.entries(testCase.factors ?? {})) {
        const stats = (factorStats[fid] ??= { correct: 0, total: 0 });
        stats.total += 1;
        if (factors[fid] === expected) stats.correct += 1;
      }
    } catch (error) {
      errors += 1;
      console.error(`case ${id}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  const report: Record<string, unknown> = {
    file,
    model,
    cases: cases.length,
    errors,
    questions: Object.fromEntries(
      Object.entries(questionStats).map(([id, s]) => [
        id,
        { ...withAccuracy(s), confusion: s.confusion },
      ]),
    ),
    factors: Object.fromEntries(
      Object.entries(factorStats).map(([id, s]) => [id, withAccuracy(s)]),
    ),
    near_threshold: nearThreshold,
    cache: cache?.stats(),
  };
  if (sweep) report.sweep = sweepFactor(sweep, predictions);
  await finishEval(report, options.report, errors);
}

async function finishEval(
  report: Record<string, unknown>,
  reportPath: string | undefined,
  errors: number,
): Promise<void> {
  if (reportPath) {
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
    console.log(reportPath);
  } else {
    console.log(JSON.stringify(report, null, 2));
  }
  if (errors > 0) process.exitCode = 1;
}

function parseJsonl(text: string, what: string, def: Definition): EvalCase[] {
  const lines = text.split(/\r?\n/);
  const cases: EvalCase[] = [];
  const errors: string[] = [];
  for (const [i, raw] of lines.entries()) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(line) as unknown;
    } catch (error) {
      errors.push(`${what}:${i + 1}: ${error instanceof Error ? error.message : String(error)}`);
      continue;
    }
    const validation = validateCase(parsed, def);
    if (validation.length > 0) {
      for (const message of validation) errors.push(`${what}:${i + 1}: ${message}`);
      continue;
    }
    cases.push(parsed as unknown as EvalCase);
  }
  if (errors.length > 0) {
    for (const message of errors) console.error(message);
    fail(`${errors.length} invalid eval case error(s)`);
  }
  return cases;
}

function validateCase(value: unknown, def: Definition): string[] {
  if (!isPlainObject(value)) return ["each case must be an object"];
  const errors: string[] = [];
  if (Object.hasOwn(value, "id") && typeof value.id !== "string") {
    errors.push("`id` must be a string");
  }
  if (!Object.hasOwn(value, "state")) {
    errors.push("each case needs a `state` field");
  } else if (!isEvalState(value.state)) {
    errors.push("`state` must be null, a string, object, or array");
  }

  if (Object.hasOwn(value, "labels")) {
    if (!isPlainObject(value.labels)) {
      errors.push("`labels` must be an object");
    } else {
      for (const [id, expected] of Object.entries(value.labels)) {
        if (!Object.hasOwn(def.questions, id)) {
          errors.push(`labels.${id}: unknown question id`);
          continue;
        }
        const question = def.questions[id]!;
        if (question.type === "choice") {
          if (typeof expected !== "string") {
            errors.push(`labels.${id}: expected a Choice label string`);
          } else if (!Object.hasOwn(question.criteria, expected)) {
            errors.push(`labels.${id}: unknown Choice label \`${expected}\``);
          }
        } else if (question.type === "noul") {
          if (typeof expected !== "boolean") {
            errors.push(`labels.${id}: expected a Noul boolean`);
          }
        } else if (
          typeof expected !== "number" ||
          !Number.isInteger(expected) ||
          expected < 0 ||
          expected >= question.criteria.length
        ) {
          errors.push(
            `labels.${id}: expected a Score integer from 0 through ${question.criteria.length - 1}`,
          );
        }
      }
    }
  }

  if (Object.hasOwn(value, "factors")) {
    if (!isPlainObject(value.factors)) {
      errors.push("`factors` must be an object");
    } else {
      for (const [id, expected] of Object.entries(value.factors)) {
        if (!Object.hasOwn(def.factorDefinitions, id)) {
          errors.push(`factors.${id}: unknown factor id`);
        } else if (typeof expected !== "boolean") {
          errors.push(`factors.${id}: expected a boolean`);
        }
      }
    }
  }
  return errors;
}

function isEvalState(value: unknown): boolean {
  return (
    isJsonValue(value) &&
    (value === null || typeof value === "string" || isPlainObject(value) || Array.isArray(value))
  );
}

function prepareSweep(id: string, def: Definition): Sweep {
  if (!Object.hasOwn(def.factorDefinitions, id)) fail(`--sweep: unknown factor \`${id}\``);
  const table = def.factorDefinitions[id]!;
  if (typeof table.ref !== "string") {
    fail(`--sweep: factor \`${id}\` is not a predicate; only predicates can be swept`);
  }
  const field = (["noul", "score", "confidence"] as const).find((candidate) =>
    isPlainObject(table[candidate]),
  );
  if (!field) fail(`--sweep: factor \`${id}\` has no numeric comparator to sweep`);
  const comparator = table[field];
  if (!isPlainObject(comparator)) fail(`--sweep: factor \`${id}\` has an invalid comparator`);
  const keys = COMPARATOR_KEYS.filter((key) => comparator[key] !== undefined);
  if (keys.length !== 1) {
    fail(`--sweep: factor \`${id}\` comparator must have exactly one operator to sweep`);
  }
  const question = def.questions[table.ref];
  const thresholds =
    field === "score" && question?.type === "score"
      ? range(0, question.criteria.length - 1, 0.1)
      : range(0.05, 0.95, 0.05);
  return { id, ref: table.ref, field, key: keys[0]!, table, thresholds };
}

function withAccuracy(t: Tally): Tally & { accuracy: number } {
  return { accuracy: t.total === 0 ? 0 : t.correct / t.total, correct: t.correct, total: t.total };
}

/** The comparable label of an answer: Choice label, Noul as `true`/`false`, Score rounded to a level. */
function labelOf(answer: unknown): string | undefined {
  if (!isPlainObject(answer)) return undefined;
  if (answer.type === "choice" && typeof answer.choice === "string") return answer.choice;
  if (answer.type === "noul" && typeof answer.noul === "number") {
    return String(answer.noul >= NOUL_CUTOFF);
  }
  if (answer.type === "score" && typeof answer.score === "number") {
    return String(Math.round(answer.score));
  }
  return undefined;
}

/** Count answers whose value sits close to a decision boundary — the ones worth inspecting. */
function recordNear(id: string, answer: unknown, dest: Record<string, number>): void {
  if (!isPlainObject(answer)) return;
  if (typeof answer.noul === "number" && Math.abs(answer.noul - NOUL_CUTOFF) <= 0.1) {
    dest[id] = (dest[id] ?? 0) + 1;
  }
  if (
    typeof answer.confidence === "number" &&
    answer.confidence >= 0.4 &&
    answer.confidence < 0.75
  ) {
    dest[`${id}.confidence`] = (dest[`${id}.confidence`] ?? 0) + 1;
  }
}

/**
 * Re-evaluate a predicate factor across a range of thresholds using the real evaluator,
 * so any other fields on the predicate (`choice = …`, a second comparator) stay in force.
 * Ground truth is the case's expected value for the factor; for a Noul predicate a
 * Boolean label on the referenced question is accepted as a fallback.
 */
function sweepFactor(sweep: Sweep, predictions: Prediction[]): unknown {
  const { id, ref, field, key, table, thresholds } = sweep;
  const rows = thresholds.map((threshold) => {
    const swept: FactorTable = { ...table, [field]: { [key]: threshold } };
    const evaluate = createFactorEvaluator({ [id]: swept });
    let correct = 0;
    let total = 0;
    for (const pred of predictions) {
      const want = groundTruth(id, ref, field, key, pred.testCase);
      if (want === undefined) continue;
      const predicted = evaluate(pred.answers)[id];
      total += 1;
      if (predicted === want) correct += 1;
    }
    return { threshold, ...withAccuracy({ correct, total }) };
  });
  return { factor: id, ref, field, comparator: key, rows };
}

function groundTruth(
  id: string,
  ref: string,
  field: "noul" | "score" | "confidence",
  key: ComparatorKey,
  testCase: EvalCase,
): boolean | undefined {
  const expected = testCase.factors?.[id];
  if (typeof expected === "boolean") return expected;
  const label = testCase.labels?.[ref];
  if (field === "noul" && typeof label === "boolean") {
    return key === "lt" || key === "lte" ? !label : label;
  }
  return undefined;
}

function range(from: number, to: number, step: number): number[] {
  const out: number[] = [];
  for (let t = from; t <= to + 1e-9; t += step) out.push(Number(t.toFixed(2)));
  return out;
}
