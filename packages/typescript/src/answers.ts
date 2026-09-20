import { isJsonValue, isPlainObject } from "./json.js";

export function isAnswerForQuestion(question: unknown, answer: unknown): boolean {
  if (!isPlainObject(question) || !isAnswerShape(answer)) return false;
  if (question.type !== answer.type) return false;

  if (question.type === "choice") {
    if (!isPlainObject(question.criteria) || typeof answer.choice !== "string") return false;
    if (!Object.hasOwn(question.criteria, answer.choice)) return false;
    const probabilities = answer.probabilities;
    if (!isPlainObject(probabilities)) return false;
    return Object.keys(question.criteria).every(
      (label) => Object.hasOwn(probabilities, label) && isFiniteNumber(probabilities[label]),
    );
  }

  if (question.type === "score") {
    if (!Array.isArray(question.criteria)) return false;
    const legend = answer.legend;
    const probabilities = answer.probabilities;
    if (!isPlainObject(legend) || !isPlainObject(probabilities)) return false;
    return question.criteria.every((_, index) => {
      const score = String(index);
      return (
        Object.hasOwn(legend, score) &&
        Object.hasOwn(probabilities, score) &&
        isFiniteNumber(probabilities[score])
      );
    });
  }

  return true;
}

export function isAnswerShape(answer: unknown): answer is Record<string, unknown> {
  if (!isPlainObject(answer) || !isJsonValue(answer)) return false;
  switch (answer.type) {
    case "noul":
      return isFiniteNumber(answer.noul);
    case "choice":
      return (
        typeof answer.choice === "string" &&
        isFiniteNumber(answer.confidence) &&
        isPlainObject(answer.probabilities)
      );
    case "score":
      return (
        isFiniteNumber(answer.score) &&
        isFiniteNumber(answer.confidence) &&
        isPlainObject(answer.legend) &&
        isPlainObject(answer.probabilities)
      );
    default:
      return false;
  }
}

export function noulValue(answer: unknown): number | undefined {
  if (!isAnswerShape(answer) || answer.type !== "noul") return undefined;
  const value = answer.noul;
  return isFiniteNumber(value) ? value : undefined;
}

export function choiceLabel(answer: unknown): string | undefined {
  if (!isAnswerShape(answer) || answer.type !== "choice") return undefined;
  return typeof answer.choice === "string" ? answer.choice : undefined;
}

export function scoreValue(answer: unknown): number | undefined {
  if (!isAnswerShape(answer) || answer.type !== "score") return undefined;
  const value = answer.score;
  return isFiniteNumber(value) ? value : undefined;
}

export function wireQuestions(
  questions: Record<
    string,
    { type: string; instructions?: unknown; criteria?: unknown; [k: string]: unknown }
  >,
): Record<string, { type: string; instructions?: unknown; criteria?: unknown }> {
  const wired = Object.create(null) as Record<
    string,
    { type: string; instructions?: unknown; criteria?: unknown }
  >;
  for (const [id, question] of Object.entries(questions)) {
    const entry: { type: string; instructions?: unknown; criteria?: unknown } = {
      type: question.type,
    };
    if (question.instructions !== undefined) entry.instructions = question.instructions;
    if (question.criteria !== undefined) entry.criteria = question.criteria;
    wired[id] = entry;
  }
  return wired;
}

export function partitionAnswers(
  questions: Record<string, unknown>,
  answers: unknown,
): { valid: Record<string, unknown>; missing: string[]; malformed: string[] } {
  const valid = Object.create(null) as Record<string, unknown>;
  const missing: string[] = [];
  const malformed: string[] = [];
  const answersObject = isPlainObject(answers) ? answers : undefined;
  for (const [id, question] of Object.entries(questions)) {
    if (answersObject === undefined || !Object.hasOwn(answersObject, id)) {
      missing.push(id);
    } else if (!isAnswerForQuestion(question, answersObject[id])) {
      malformed.push(id);
    } else {
      valid[id] = answersObject[id];
    }
  }
  return { valid, missing, malformed };
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
