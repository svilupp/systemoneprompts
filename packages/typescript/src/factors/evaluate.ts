import { diagnostic, errorsOf, SystemOnePromptsError } from "../definition/diagnostics.js";
import { isPlainObject } from "../json.js";
import type { Questions, SystemOneResult } from "../native.js";
import { topoSortFactors } from "./graph.js";
import type { Comparator, FactorDef, FactorTable } from "./schema.js";
import { parseFactors } from "./schema.js";

/** The `answers` object System One returns for a set of questions. */
export type AnswersFor<Q extends Questions> = SystemOneResult<Q>["answers"];

/** A bare Noul reference in a Boolean context means `noul >= 0.5`. Fixed by design. */
export const NOUL_CUTOFF = 0.5;

/**
 * Compile verbatim factor tables into a pure evaluator: answers in, Booleans out.
 * Structural problems and cycles throw here; missing answers throw at evaluation time
 * (never silently `false`, which `not` would flip into a wrong `true`).
 */
export function createFactorEvaluator<Q extends Questions = Questions, F = Record<string, boolean>>(
  defs: Record<string, FactorTable>,
): (answers: AnswersFor<Q>) => F {
  if (!isPlainObject(defs)) {
    throw new SystemOnePromptsError(
      diagnostic(
        "error",
        "factors-not-table",
        "createFactorEvaluator expects the factor tables (definition.factorDefinitions)",
      ),
    );
  }
  const parsed = parseFactors(defs, new Set());
  const errors = errorsOf(parsed.diagnostics);
  if (errors.length > 0) throw new SystemOnePromptsError(errors);
  const sorted = topoSortFactors(parsed.factors, () => ({}));
  if (sorted.diagnostics.length > 0) throw new SystemOnePromptsError(sorted.diagnostics);
  const factors = parsed.factors;
  const order = sorted.order;
  const factorIds = Object.keys(defs);

  return (answers: AnswersFor<Q>): F => {
    const resolved = new Map<string, boolean>();
    for (const id of order) {
      const factor = factors[id];
      if (!factor) continue;
      resolved.set(id, evaluateFactor(id, factor, answers, resolved, factors));
    }
    const out: Record<string, boolean> = Object.create(null);
    for (const id of factorIds) {
      out[id] = resolved.get(id) ?? false;
    }
    return out as F;
  };
}

function evaluateFactor(
  id: string,
  factor: FactorDef,
  answers: Record<string, unknown>,
  resolved: Map<string, boolean>,
  factors: Record<string, FactorDef>,
): boolean {
  switch (factor.kind) {
    case "predicate":
      return evaluatePredicate(id, factor, answers);
    case "not":
      return !resolveBoolean(factor.of, answers, resolved, factors);
    case "all": {
      let result = true;
      for (const ref of factor.of) {
        if (!resolveBoolean(ref, answers, resolved, factors)) result = false;
      }
      return result;
    }
    case "any": {
      let result = false;
      for (const ref of factor.of) {
        if (resolveBoolean(ref, answers, resolved, factors)) result = true;
      }
      return result;
    }
    case "at_least": {
      let count = 0;
      for (const ref of factor.of) {
        if (resolveBoolean(ref, answers, resolved, factors)) count += 1;
      }
      return count >= factor.count;
    }
  }
}

function resolveBoolean(
  ref: string,
  answers: Record<string, unknown>,
  resolved: Map<string, boolean>,
  factors: Record<string, FactorDef>,
): boolean {
  if (resolved.has(ref)) return resolved.get(ref) ?? false;
  if (Object.hasOwn(factors, ref)) {
    throw new SystemOnePromptsError(
      diagnostic(
        "error",
        "factor-order",
        `factor \`${ref}\` was referenced before it was evaluated`,
      ),
    );
  }
  const answer = requireAnswer(ref, answers);
  if (!isPlainObject(answer) || !Object.hasOwn(answer, "noul") || typeof answer.noul !== "number") {
    throw new SystemOnePromptsError(
      diagnostic(
        "error",
        "non-noul-runtime",
        `reference \`${ref}\` is not a Noul answer; wrap Choice/Score in a predicate`,
      ),
    );
  }
  requireFiniteNumber(`answer \`${ref}\``, "noul", answer.noul);
  return answer.noul >= NOUL_CUTOFF;
}

function hasValueChecks(factor: Extract<FactorDef, { kind: "predicate" }>): boolean {
  return (
    factor.choice !== undefined ||
    factor.noul !== undefined ||
    factor.score !== undefined ||
    factor.confidence !== undefined
  );
}

/**
 * Known-answer rule aligned with pi-start-smart `isKnownAnswer`:
 * explicit `missing`, confidence 0, and a bare Noul of 0.5 are unknown.
 * Missing answers are unknown (not an error) when the predicate asks about known-ness.
 */
export function isKnownNativeAnswer(answer: unknown): boolean {
  if (!isPlainObject(answer)) return false;
  if (answer.missing === true) return false;
  if (Object.hasOwn(answer, "confidence")) {
    if (typeof answer.confidence !== "number" || !Number.isFinite(answer.confidence)) return false;
    return answer.confidence !== 0;
  }
  if (Object.hasOwn(answer, "noul")) {
    if (typeof answer.noul !== "number" || !Number.isFinite(answer.noul)) return false;
    return answer.noul !== NOUL_CUTOFF;
  }
  if (typeof answer.choice === "string") return true;
  if (typeof answer.score === "number") return Number.isFinite(answer.score);
  return false;
}

function lookupAnswer(id: string, answers: Record<string, unknown>): unknown {
  if (!Object.hasOwn(answers, id)) return undefined;
  return answers[id];
}

function evaluatePredicate(
  id: string,
  factor: Extract<FactorDef, { kind: "predicate" }>,
  answers: Record<string, unknown>,
): boolean {
  const lookedUp = lookupAnswer(factor.ref, answers);
  const known = isKnownNativeAnswer(lookedUp);

  if (factor.known !== undefined) {
    if (factor.known !== known) return false;
    if (!hasValueChecks(factor)) return true;
    // known=false matched: the answer is unknown. Value comparisons still
    // need a body and throw if it is missing (not coerced to false).
    if (factor.known === false && (lookedUp == null || !isPlainObject(lookedUp))) {
      throw new SystemOnePromptsError(
        diagnostic("error", "missing-answer", `missing answer \`${factor.ref}\``),
      );
    }
  }

  const answer = requireAnswer(factor.ref, answers);
  if (!isPlainObject(answer)) {
    throw new SystemOnePromptsError(
      diagnostic("error", "invalid-answer", `answer \`${factor.ref}\` is not an object`),
    );
  }

  const checks: boolean[] = [];
  if (factor.choice !== undefined) {
    if (!Object.hasOwn(answer, "choice") || typeof answer.choice !== "string") {
      throw new SystemOnePromptsError(
        diagnostic(
          "error",
          "missing-choice-field",
          `factor \`${id}\` expected Choice answer \`${factor.ref}\` to have a choice field`,
        ),
      );
    }
    checks.push(answer.choice === factor.choice);
  }
  if (factor.noul !== undefined) {
    if (!Object.hasOwn(answer, "noul") || typeof answer.noul !== "number") {
      throw new SystemOnePromptsError(
        diagnostic(
          "error",
          "missing-noul-field",
          `factor \`${id}\` expected Noul answer \`${factor.ref}\` to have a noul field`,
        ),
      );
    }
    requireFiniteNumber(`factor \`${id}\` answer \`${factor.ref}\``, "noul", answer.noul);
    checks.push(compare(answer.noul, factor.noul));
  }
  if (factor.score !== undefined) {
    if (!Object.hasOwn(answer, "score") || typeof answer.score !== "number") {
      throw new SystemOnePromptsError(
        diagnostic(
          "error",
          "missing-score-field",
          `factor \`${id}\` expected Score answer \`${factor.ref}\` to have a score field`,
        ),
      );
    }
    requireFiniteNumber(`factor \`${id}\` answer \`${factor.ref}\``, "score", answer.score);
    checks.push(compare(answer.score, factor.score));
  }
  if (factor.confidence !== undefined) {
    if (!Object.hasOwn(answer, "confidence") || typeof answer.confidence !== "number") {
      throw new SystemOnePromptsError(
        diagnostic(
          "error",
          "missing-confidence-field",
          `factor \`${id}\` expected \`${factor.ref}\` to have a confidence field`,
        ),
      );
    }
    requireFiniteNumber(
      `factor \`${id}\` answer \`${factor.ref}\``,
      "confidence",
      answer.confidence,
    );
    checks.push(compare(answer.confidence, factor.confidence));
  }
  return checks.every(Boolean);
}

function requireAnswer(id: string, answers: Record<string, unknown>): unknown {
  if (!Object.hasOwn(answers, id) || answers[id] == null) {
    throw new SystemOnePromptsError(
      diagnostic("error", "missing-answer", `missing answer \`${id}\``),
    );
  }
  return answers[id];
}

/** All comparators present in `cmp` must hold (they are ANDed). */
export function compare(value: number, cmp: Comparator): boolean {
  requireFiniteNumber("comparison", "value", value);
  for (const key of ["gt", "gte", "lt", "lte"] as const) {
    if (cmp[key] !== undefined) requireFiniteNumber("comparison", key, cmp[key]);
  }
  if (cmp.gt !== undefined && !(value > cmp.gt)) return false;
  if (cmp.gte !== undefined && !(value >= cmp.gte)) return false;
  if (cmp.lt !== undefined && !(value < cmp.lt)) return false;
  if (cmp.lte !== undefined && !(value <= cmp.lte)) return false;
  return true;
}

function requireFiniteNumber(context: string, field: string, value: number): void {
  if (!Number.isFinite(value)) {
    throw new SystemOnePromptsError(
      diagnostic("error", "nonfinite-number", `${context} field \`${field}\` must be finite`),
    );
  }
}
