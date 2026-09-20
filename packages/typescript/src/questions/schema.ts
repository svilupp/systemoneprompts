import type { Diagnostic, SourceLocation } from "../definition/diagnostics.js";
import { diagnostic } from "../definition/diagnostics.js";
import { locate, type SourceIndex } from "../definition/locate.js";
import { isJsonValue, isPlainObject } from "../json.js";
import type { Question, Questions } from "../native.js";

export const QUESTION_TYPES = ["noul", "choice", "score"] as const;
export type QuestionType = (typeof QUESTION_TYPES)[number];

const MAX_CHOICE_LABELS = 255;
const QUESTION_FIELDS = new Set(["type", "instructions", "criteria"]);

/** What factor validation needs to know about a question: its primitive and, for Choice, its labels. */
export interface QuestionInfo {
  id: string;
  type: QuestionType;
  choiceLabels?: string[];
}

export function questionInfos(questions: Questions): Map<string, QuestionInfo> {
  const infos = new Map<string, QuestionInfo>();
  for (const [id, question] of Object.entries(questions)) {
    infos.set(id, {
      id,
      type: question.type,
      ...(question.type === "choice" ? { choiceLabels: Object.keys(question.criteria) } : {}),
    });
  }
  return infos;
}

export function validateQuestions(
  raw: unknown,
  index: SourceIndex,
): { questions: Questions; infos: Map<string, QuestionInfo>; diagnostics: Diagnostic[] } {
  const diagnostics: Diagnostic[] = [];
  const questions: Questions = Object.create(null);
  const infos = new Map<string, QuestionInfo>();

  if (raw == null || (isPlainObject(raw) && Object.keys(raw).length === 0)) {
    diagnostics.push(
      diagnostic(
        "error",
        "questions-empty",
        "[questions] must contain at least one question",
        locate(index, { table: "questions" }),
      ),
    );
    return { questions, infos, diagnostics };
  }
  if (!isPlainObject(raw)) {
    diagnostics.push(
      diagnostic(
        "error",
        "questions-not-table",
        "[questions] must be a table of question objects",
        locate(index, { table: "questions" }),
      ),
    );
    return { questions, infos, diagnostics };
  }

  for (const [id, value] of Object.entries(raw)) {
    const loc = locate(index, { table: `questions.${id}`, section: "questions", key: id });
    const result = validateQuestion(id, value, loc);
    diagnostics.push(...result.diagnostics);
    if (result.question && result.info) {
      questions[id] = result.question;
      infos.set(id, result.info);
    }
  }

  return { questions, infos, diagnostics };
}

function validateQuestion(
  id: string,
  value: unknown,
  loc: SourceLocation,
): { question?: Questions[string]; info?: QuestionInfo; diagnostics: Diagnostic[] } {
  const diagnostics: Diagnostic[] = [];
  if (!isPlainObject(value)) {
    diagnostics.push(
      diagnostic("error", "question-not-table", `question \`${id}\` must be a table`, loc),
    );
    return { diagnostics };
  }

  const extraKeys = Object.keys(value).filter((k) => !QUESTION_FIELDS.has(k));
  for (const key of extraKeys) {
    diagnostics.push(
      diagnostic(
        "error",
        "unknown-question-field",
        `question \`${id}\` has unknown field \`${key}\``,
        loc,
        "only `type`, `instructions`, and `criteria` are allowed",
      ),
    );
  }

  const type = value.type;
  if (type !== "noul" && type !== "choice" && type !== "score") {
    diagnostics.push(
      diagnostic(
        "error",
        "invalid-question-type",
        `question \`${id}\` has ${type == null ? "missing" : `invalid`} type ${type == null ? "" : `\`${String(type)}\``}`.trim(),
        loc,
        'type must be "noul", "choice", or "score"',
      ),
    );
    return { diagnostics };
  }

  if (value.instructions !== undefined && !isEntryType(value.instructions)) {
    diagnostics.push(
      diagnostic(
        "error",
        "invalid-instructions",
        `question \`${id}\` instructions must be a string, table, or array`,
        loc,
      ),
    );
    return { diagnostics };
  }

  if (type === "noul") {
    return validateNoul(id, value, loc, diagnostics);
  }
  if (type === "choice") {
    return validateChoice(id, value, loc, diagnostics);
  }
  return validateScore(id, value, loc, diagnostics);
}

function validateNoul(
  id: string,
  value: Record<string, unknown>,
  loc: SourceLocation,
  diagnostics: Diagnostic[],
): { question?: Questions[string]; info?: QuestionInfo; diagnostics: Diagnostic[] } {
  if (value.criteria != null) {
    if (!isPlainObject(value.criteria)) {
      diagnostics.push(
        diagnostic(
          "error",
          "noul-criteria",
          `Noul \`${id}\` criteria must be a table with optional true/false keys`,
          loc,
        ),
      );
      return { diagnostics };
    }
    const unknown = Object.keys(value.criteria).filter((k) => k !== "true" && k !== "false");
    if (unknown.length > 0) {
      diagnostics.push(
        diagnostic(
          "error",
          "noul-criteria-keys",
          `Noul \`${id}\` criteria may only contain true/false; found ${unknown.map((k) => `\`${k}\``).join(", ")}`,
          loc,
        ),
      );
      return { diagnostics };
    }
    for (const key of ["true", "false"] as const) {
      const entry = value.criteria[key];
      if (entry !== undefined && !isEntryType(entry)) {
        diagnostics.push(
          diagnostic(
            "error",
            "noul-criteria-entry",
            `Noul \`${id}\` criteria.${key} must be a string, table, or array`,
            loc,
          ),
        );
        return { diagnostics };
      }
    }
  }

  const question = stripUndefined({
    type: "noul" as const,
    ...(value.instructions !== undefined
      ? { instructions: value.instructions as Question["instructions"] }
      : {}),
    ...(value.criteria !== undefined
      ? { criteria: value.criteria as NonNullable<Extract<Question, { type: "noul" }>["criteria"]> }
      : {}),
  }) as Question;
  return { question, info: { id, type: "noul" }, diagnostics };
}

function validateChoice(
  id: string,
  value: Record<string, unknown>,
  loc: SourceLocation,
  diagnostics: Diagnostic[],
): { question?: Questions[string]; info?: QuestionInfo; diagnostics: Diagnostic[] } {
  if (!isPlainObject(value.criteria)) {
    diagnostics.push(
      diagnostic(
        "error",
        "choice-criteria",
        `Choice \`${id}\` requires a non-empty criteria table`,
        loc,
      ),
    );
    return { diagnostics };
  }
  const labels = Object.keys(value.criteria);
  if (labels.length === 0) {
    diagnostics.push(
      diagnostic(
        "error",
        "choice-criteria-empty",
        `Choice \`${id}\` criteria must not be empty`,
        loc,
      ),
    );
    return { diagnostics };
  }
  if (labels.length > MAX_CHOICE_LABELS) {
    diagnostics.push(
      diagnostic(
        "error",
        "choice-criteria-limit",
        `Choice \`${id}\` has ${labels.length} labels; maximum is ${MAX_CHOICE_LABELS}`,
        loc,
      ),
    );
    return { diagnostics };
  }
  for (const [label, entry] of Object.entries(value.criteria)) {
    if (!isEntryType(entry)) {
      diagnostics.push(
        diagnostic(
          "error",
          "choice-criteria-entry",
          `Choice \`${id}\` criteria.${label} must be a string, table, or array`,
          loc,
        ),
      );
      return { diagnostics };
    }
  }

  const question = stripUndefined({
    type: "choice" as const,
    ...(value.instructions !== undefined
      ? { instructions: value.instructions as Question["instructions"] }
      : {}),
    criteria: value.criteria,
  }) as Question;
  return { question, info: { id, type: "choice", choiceLabels: labels }, diagnostics };
}

function validateScore(
  id: string,
  value: Record<string, unknown>,
  loc: SourceLocation,
  diagnostics: Diagnostic[],
): { question?: Questions[string]; info?: QuestionInfo; diagnostics: Diagnostic[] } {
  if (!Array.isArray(value.criteria)) {
    diagnostics.push(
      diagnostic(
        "error",
        "score-criteria",
        `Score \`${id}\` requires criteria as an array of at least 2 entries`,
        loc,
      ),
    );
    return { diagnostics };
  }
  if (value.criteria.length < 2) {
    diagnostics.push(
      diagnostic(
        "error",
        "score-criteria-min",
        `Score \`${id}\` criteria must have at least 2 entries`,
        loc,
      ),
    );
    return { diagnostics };
  }
  for (let i = 0; i < value.criteria.length; i++) {
    const entry = value.criteria[i];
    if (!isEntryType(entry)) {
      diagnostics.push(
        diagnostic(
          "error",
          "score-criteria-entry",
          `Score \`${id}\` criteria[${i}] must be a string, table, or array`,
          loc,
        ),
      );
      return { diagnostics };
    }
  }

  const question = stripUndefined({
    type: "score" as const,
    ...(value.instructions !== undefined
      ? { instructions: value.instructions as Question["instructions"] }
      : {}),
    criteria: value.criteria as [unknown, unknown, ...unknown[]],
  }) as Question;
  return { question, info: { id, type: "score" }, diagnostics };
}

function isEntryType(value: unknown): boolean {
  if (value === null) return true;
  if (typeof value === "string") return true;
  if (Array.isArray(value) || isPlainObject(value)) return isJsonValue(value);
  return false;
}

function stripUndefined<T extends Record<string, unknown>>(value: T): T {
  const out = { ...value };
  for (const [key, entry] of Object.entries(out)) {
    if (entry === undefined) delete out[key];
  }
  return out;
}
