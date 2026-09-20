import type { Diagnostic, SourceLocation } from "../definition/diagnostics.js";
import { diagnostic } from "../definition/diagnostics.js";
import { EMPTY_INDEX, locate, type SourceIndex } from "../definition/locate.js";
import { isPlainObject } from "../json.js";
import type { QuestionInfo } from "../questions/schema.js";

export const COMPARATOR_KEYS = ["gt", "gte", "lt", "lte"] as const;
export type ComparatorKey = (typeof COMPARATOR_KEYS)[number];

export type Comparator = {
  gt?: number;
  gte?: number;
  lt?: number;
  lte?: number;
};

export type PredicateFactor = {
  kind: "predicate";
  ref: string;
  /** Require a known (or unknown) answer before other predicate fields. */
  known?: boolean;
  choice?: string;
  noul?: Comparator;
  score?: Comparator;
  confidence?: Comparator;
};

export type AllFactor = { kind: "all"; of: string[] };
export type AnyFactor = { kind: "any"; of: string[] };
export type NotFactor = { kind: "not"; of: string };
export type AtLeastFactor = { kind: "at_least"; count: number; of: string[] };

export type FactorDef = PredicateFactor | AllFactor | AnyFactor | NotFactor | AtLeastFactor;

/** One verbatim `[factors]` inline table, e.g. `{ ref = "topic", choice = "billing" }`. */
export type FactorTable = Record<string, unknown>;

const OPERATOR_KEYS = ["all", "any", "not", "at_least"] as const;
const OPERATOR_ALLOWED_KEYS: Record<(typeof OPERATOR_KEYS)[number], ReadonlySet<string>> = {
  all: new Set(["all"]),
  any: new Set(["any"]),
  not: new Set(["not"]),
  at_least: new Set(["at_least", "of"]),
};
const PREDICATE_ALLOWED_KEYS = new Set(["ref", "known", "choice", "noul", "score", "confidence"]);

export function parseFactors(
  raw: unknown,
  questionIds: ReadonlySet<string>,
  index: SourceIndex = EMPTY_INDEX,
): {
  factors: Record<string, FactorDef>;
  factorDefinitions: Record<string, FactorTable>;
  diagnostics: Diagnostic[];
} {
  const diagnostics: Diagnostic[] = [];
  const factors: Record<string, FactorDef> = Object.create(null);
  const factorDefinitions: Record<string, FactorTable> = Object.create(null);

  if (raw == null) return { factors, factorDefinitions, diagnostics };
  if (!isPlainObject(raw)) {
    diagnostics.push(
      diagnostic(
        "error",
        "factors-not-table",
        "[factors] must be a table of Boolean derivations",
        locate(index, { table: "factors" }),
      ),
    );
    return { factors, factorDefinitions, diagnostics };
  }

  for (const [id, value] of Object.entries(raw)) {
    const loc = locate(index, { section: "factors", key: id, table: "factors" });
    if (questionIds.has(id)) {
      diagnostics.push(
        diagnostic(
          "error",
          "id-collision",
          `factor \`${id}\` collides with question \`${id}\``,
          loc,
        ),
      );
      continue;
    }
    if (!isPlainObject(value)) {
      diagnostics.push(
        diagnostic("error", "factor-not-table", `factor \`${id}\` must be an inline table`, loc),
      );
      continue;
    }
    const parsed = parseFactor(id, value, loc);
    diagnostics.push(...parsed.diagnostics);
    if (parsed.factor) {
      factors[id] = parsed.factor;
      factorDefinitions[id] = value;
    }
  }

  return { factors, factorDefinitions, diagnostics };
}

function parseFactor(
  id: string,
  value: Record<string, unknown>,
  loc: SourceLocation,
): { factor?: FactorDef; diagnostics: Diagnostic[] } {
  const diagnostics: Diagnostic[] = [];
  const hasRef = Object.hasOwn(value, "ref");
  const operators = OPERATOR_KEYS.filter((key) => Object.hasOwn(value, key));
  if (hasRef && operators.length > 0) {
    diagnostics.push(
      diagnostic(
        "error",
        "factor-mixed",
        `factor \`${id}\` cannot mix a predicate \`ref\` with Boolean operators`,
        loc,
      ),
    );
    return { diagnostics };
  }
  if (operators.length > 1) {
    diagnostics.push(
      diagnostic(
        "error",
        "factor-mixed",
        `factor \`${id}\` uses several operators (${operators.join(", ")}); use exactly one`,
        loc,
        "nest them as separate factors instead",
      ),
    );
    return { diagnostics };
  }
  const allowedKeys = hasRef
    ? PREDICATE_ALLOWED_KEYS
    : OPERATOR_ALLOWED_KEYS[operators[0] ?? "at_least"];
  const unknown = Object.keys(value).filter((k) => !allowedKeys.has(k));
  for (const key of unknown) {
    diagnostics.push(
      diagnostic(
        "error",
        "unknown-factor-field",
        `factor \`${id}\` has unknown field \`${key}\``,
        loc,
      ),
    );
  }
  if (unknown.length > 0) return { diagnostics };

  if (hasRef) {
    return parsePredicate(id, value, loc, diagnostics);
  }
  if (Object.hasOwn(value, "at_least") || (Object.hasOwn(value, "of") && operators.length === 0)) {
    return parseAtLeast(id, value, loc, diagnostics);
  }
  if (Object.hasOwn(value, "all")) {
    const of = readStringList(id, "all", value.all, loc, diagnostics);
    if (!of) return { diagnostics };
    return { factor: { kind: "all", of }, diagnostics };
  }
  if (Object.hasOwn(value, "any")) {
    const of = readStringList(id, "any", value.any, loc, diagnostics);
    if (!of) return { diagnostics };
    return { factor: { kind: "any", of }, diagnostics };
  }
  if (Object.hasOwn(value, "not")) {
    if (typeof value.not !== "string") {
      diagnostics.push(
        diagnostic("error", "factor-not", `factor \`${id}\` \`not\` must be a string id`, loc),
      );
      return { diagnostics };
    }
    return { factor: { kind: "not", of: value.not }, diagnostics };
  }

  diagnostics.push(
    diagnostic(
      "error",
      "factor-empty",
      `factor \`${id}\` must be a predicate or a Boolean operator`,
      loc,
      "use ref / all / any / not / at_least",
    ),
  );
  return { diagnostics };
}

function parsePredicate(
  id: string,
  value: Record<string, unknown>,
  loc: SourceLocation,
  diagnostics: Diagnostic[],
): { factor?: FactorDef; diagnostics: Diagnostic[] } {
  if (typeof value.ref !== "string" || value.ref === "") {
    diagnostics.push(
      diagnostic("error", "predicate-ref", `factor \`${id}\` \`ref\` must be a question id`, loc),
    );
    return { diagnostics };
  }

  const factor: PredicateFactor = { kind: "predicate", ref: value.ref };
  if (Object.hasOwn(value, "known")) {
    if (typeof value.known !== "boolean") {
      diagnostics.push(
        diagnostic("error", "predicate-known", `factor \`${id}\` \`known\` must be a boolean`, loc),
      );
      return { diagnostics };
    }
    factor.known = value.known;
  }
  if (Object.hasOwn(value, "choice")) {
    if (typeof value.choice !== "string") {
      diagnostics.push(
        diagnostic(
          "error",
          "predicate-choice",
          `factor \`${id}\` \`choice\` must be a string label`,
          loc,
        ),
      );
      return { diagnostics };
    }
    factor.choice = value.choice;
  }
  for (const field of ["noul", "score", "confidence"] as const) {
    if (!Object.hasOwn(value, field) || value[field] === undefined) continue;
    const cmp = parseComparator(id, field, value[field], loc, diagnostics);
    if (!cmp) return { diagnostics };
    factor[field] = cmp;
  }

  if (
    factor.known === undefined &&
    factor.choice === undefined &&
    factor.noul === undefined &&
    factor.score === undefined &&
    factor.confidence === undefined
  ) {
    diagnostics.push(
      diagnostic(
        "error",
        "predicate-empty",
        `factor \`${id}\` predicate needs one of known / choice / noul / score / confidence`,
        loc,
      ),
    );
    return { diagnostics };
  }

  return { factor, diagnostics };
}

function parseAtLeast(
  id: string,
  value: Record<string, unknown>,
  loc: SourceLocation,
  diagnostics: Diagnostic[],
): { factor?: FactorDef; diagnostics: Diagnostic[] } {
  if (
    typeof value.at_least !== "number" ||
    !Number.isInteger(value.at_least) ||
    value.at_least < 1
  ) {
    diagnostics.push(
      diagnostic(
        "error",
        "at-least-count",
        `factor \`${id}\` \`at_least\` must be a positive integer`,
        loc,
      ),
    );
    return { diagnostics };
  }
  const of = readStringList(id, "of", value.of, loc, diagnostics);
  if (!of) return { diagnostics };
  return { factor: { kind: "at_least", count: value.at_least, of }, diagnostics };
}

function parseComparator(
  id: string,
  field: string,
  value: unknown,
  loc: SourceLocation,
  diagnostics: Diagnostic[],
): Comparator | undefined {
  if (!isPlainObject(value)) {
    diagnostics.push(
      diagnostic(
        "error",
        "comparator-table",
        `factor \`${id}\` \`${field}\` must be a comparator table`,
        loc,
        "e.g. { gte = 0.75 }",
      ),
    );
    return undefined;
  }
  const unknown = Object.keys(value).filter((k) => !COMPARATOR_KEYS.includes(k as ComparatorKey));
  if (unknown.length > 0) {
    diagnostics.push(
      diagnostic(
        "error",
        "comparator-keys",
        `factor \`${id}\` \`${field}\` has unknown comparator ${unknown.map((k) => `\`${k}\``).join(", ")}`,
        loc,
        "use gt, gte, lt, lte",
      ),
    );
    return undefined;
  }
  const cmp: Comparator = {};
  for (const key of COMPARATOR_KEYS) {
    if (!Object.hasOwn(value, key) || value[key] === undefined) continue;
    if (typeof value[key] !== "number" || !Number.isFinite(value[key])) {
      diagnostics.push(
        diagnostic(
          "error",
          "comparator-number",
          `factor \`${id}\` \`${field}.${key}\` must be a finite number`,
          loc,
        ),
      );
      return undefined;
    }
    cmp[key] = value[key];
  }
  if (Object.keys(cmp).length === 0) {
    diagnostics.push(
      diagnostic(
        "error",
        "comparator-empty",
        `factor \`${id}\` \`${field}\` needs at least one of gt/gte/lt/lte`,
        loc,
      ),
    );
    return undefined;
  }
  return cmp;
}

function readStringList(
  id: string,
  field: string,
  value: unknown,
  loc: SourceLocation,
  diagnostics: Diagnostic[],
): string[] | undefined {
  if (
    !Array.isArray(value) ||
    value.length === 0 ||
    value.some((item) => typeof item !== "string")
  ) {
    diagnostics.push(
      diagnostic(
        "error",
        "factor-list",
        `factor \`${id}\` \`${field}\` must be a non-empty array of ids`,
        loc,
      ),
    );
    return undefined;
  }
  return [...value] as string[];
}

export function referencedIds(factor: FactorDef): string[] {
  switch (factor.kind) {
    case "predicate":
      return [factor.ref];
    case "not":
      return [factor.of];
    case "all":
    case "any":
    case "at_least":
      return factor.of;
  }
}

/**
 * Check a factor's references against the questions they name: unknown ids,
 * Choice/Score used as Booleans, predicate fields that the primitive does not carry,
 * and unknown Choice labels.
 */
export function validatePrimitiveRefs(
  id: string,
  factor: FactorDef,
  questions: ReadonlyMap<string, QuestionInfo>,
  factorIds: ReadonlySet<string>,
  loc: SourceLocation,
): Diagnostic[] {
  const diagnostics: Diagnostic[] = [];

  if (factor.kind === "predicate") {
    const q = questions.get(factor.ref);
    if (!q) {
      diagnostics.push(
        diagnostic(
          "error",
          "unknown-ref",
          `factor \`${id}\` references unknown question \`${factor.ref}\``,
          loc,
        ),
      );
      return diagnostics;
    }
    if (factor.choice !== undefined) {
      if (q.type !== "choice") {
        diagnostics.push(
          diagnostic(
            "error",
            "choice-on-non-choice",
            `\`choice\` is not available on ${capitalize(q.type)} \`${factor.ref}\``,
            loc,
          ),
        );
      } else if (!q.choiceLabels?.includes(factor.choice)) {
        diagnostics.push(
          diagnostic(
            "error",
            "unknown-option",
            `factor \`${id}\` references Choice \`${factor.ref}\` with unknown option \`${factor.choice}\``,
            loc,
            `available: ${q.choiceLabels?.join(", ") ?? ""}`,
          ),
        );
      }
    }
    if (factor.noul !== undefined && q.type !== "noul") {
      diagnostics.push(
        diagnostic(
          "error",
          "noul-on-non-noul",
          `\`noul\` is not available on ${capitalize(q.type)} \`${factor.ref}\``,
          loc,
        ),
      );
    }
    if (factor.score !== undefined && q.type !== "score") {
      diagnostics.push(
        diagnostic(
          "error",
          "score-on-non-score",
          `\`score\` is not available on ${capitalize(q.type)} \`${factor.ref}\``,
          loc,
        ),
      );
    }
    if (factor.confidence !== undefined && q.type === "noul") {
      diagnostics.push(
        diagnostic(
          "error",
          "noul-confidence",
          `\`confidence\` is not available on Noul \`${factor.ref}\` (Noul answers carry only \`noul\`)`,
          loc,
        ),
      );
    }
    return diagnostics;
  }

  for (const ref of referencedIds(factor)) {
    if (factorIds.has(ref) || questions.has(ref)) {
      const q = questions.get(ref);
      if (q && q.type !== "noul") {
        diagnostics.push(
          diagnostic(
            "error",
            "non-boolean-ref",
            `${capitalize(q.type)} \`${ref}\` used directly in \`${factor.kind}\`; wrap it in a predicate: { ref = "${ref}", ${q.type === "choice" ? 'choice = "…"' : "score = { gte = … }"} }`,
            loc,
          ),
        );
      }
      continue;
    }
    diagnostics.push(
      diagnostic("error", "unknown-ref", `factor \`${id}\` references unknown id \`${ref}\``, loc),
    );
  }
  return diagnostics;
}

function capitalize(value: string): string {
  return value.length === 0 ? value : value[0]!.toUpperCase() + value.slice(1);
}
