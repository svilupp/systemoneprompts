import { indexSource } from "./definition/locate.js";
import { canonicalJson, isJsonValue, isPlainObject } from "./json.js";
import type { Questions, SystemOneResult } from "./native.js";
import { validateQuestions } from "./questions/schema.js";

export class OpenAIDecisionsError extends Error {
  readonly kind: "http" | "transport" | "timeout" | "response" | "refusal" | "compatibility";
  readonly body: unknown;
  readonly status?: number;
  readonly requestId?: string;
  readonly retryAfter?: number;
  readonly refusedIds?: string[];
  readonly code?: string;
  constructor(
    message: string,
    details: {
      kind: OpenAIDecisionsError["kind"];
      body?: unknown;
      status?: number;
      requestId?: string;
      retryAfter?: number;
      refusedIds?: string[];
      code?: string;
    },
  ) {
    super(message);
    this.name = "OpenAIDecisionsError";
    this.kind = details.kind;
    this.body = details.body;
    this.status = details.status;
    this.requestId = details.requestId;
    this.retryAfter = details.retryAfter;
    this.refusedIds = details.refusedIds;
    this.code = details.code;
  }
}

const fallback = "Evaluate the supplied evidence against the criteria.";
export function incompatible(code: string, message: string): never {
  throw new OpenAIDecisionsError(`${code}: ${message}`, { kind: "compatibility", code });
}
export function modelName(value: unknown): string {
  if (typeof value !== "string" || !value.trim())
    incompatible("openai-model-empty", "model must be a nonblank string");
  return value;
}
function empty(value: unknown): boolean {
  return (
    value == null ||
    (typeof value === "string" && !value.trim()) ||
    (typeof value === "object" && Object.keys(value).length === 0)
  );
}
function render(value: unknown): string {
  return typeof value === "string" ? value : canonicalJson(value);
}
export function encodeDecisionsRequest(state: unknown, questions: Questions, model: string) {
  if (!isJsonValue(state)) incompatible("openai-state-json", "state must be JSON-compatible");
  const checked = validateQuestions(questions, indexSource(""));
  const errors = checked.diagnostics.filter((d) => d.severity === "error");
  if (errors.length) incompatible(errors[0]!.code, errors.map((d) => d.message).join("; "));
  const ids = Object.keys(questions);
  const wire = ids.map((id, i) => {
    const question = questions[id]!;
    let instructions = empty(question.instructions) ? fallback : render(question.instructions);
    const name = `q${i}`;
    if (question.type === "noul") {
      if (empty(question.instructions) && Object.values(question.criteria ?? {}).every(empty))
        incompatible(
          "openai-question-empty",
          `question ${id} needs instructions or outcome criteria`,
        );
      if (question.criteria && Object.keys(question.criteria).length)
        instructions += `\nOutcome criteria (JSON): ${canonicalJson(question.criteria)}`;
      return { type: "predicate", name, instructions };
    }
    if (question.type === "choice") {
      if (Object.keys(question.criteria).length < 2)
        incompatible("openai-choice-min-options", `question ${id} needs at least two options`);
      return {
        type: "choice",
        name,
        instructions,
        choices: Object.entries(question.criteria).map(([value, description]) => ({
          value,
          ...(description === null ? {} : { description: render(description) }),
        })),
      };
    }
    return {
      type: "score",
      name,
      instructions,
      levels: question.criteria.map((description, i) => ({
        label: String(i),
        ...(description === null ? {} : { description: render(description) }),
      })),
    };
  });
  return { body: { model: modelName(model), input: render(state), questions: wire }, ids };
}

export function decodeDecisionsResponse<Q extends Questions>(
  raw: unknown,
  questions: Q,
  ids: string[],
): SystemOneResult<Q> {
  function invalid(message: string): never {
    throw new OpenAIDecisionsError(`Invalid Decisions response: ${message}`, {
      kind: "response",
      body: raw,
    });
  }
  if (
    !isPlainObject(raw) ||
    typeof raw.model !== "string" ||
    !Array.isArray(raw.answers) ||
    !isPlainObject(raw.usage)
  )
    invalid("model, answers, and usage are required");
  const usage = raw.usage;
  for (const key of ["input_tokens", "output_tokens"]) {
    const n = usage[key];
    if (typeof n !== "number" || !Number.isInteger(n) || n < 0) invalid(`invalid ${key}`);
  }
  const seen = new Set<string>();
  const refusedIds: string[] = [];
  const answers: Record<string, unknown> = Object.create(null);
  const names = new Map(ids.map((id, i) => [`q${i}`, id]));
  function probability(n: unknown): number {
    if (typeof n !== "number" || !Number.isFinite(n) || n < 0 || n > 1)
      invalid("invalid probability/confidence");
    return n;
  }
  for (const answer of raw.answers) {
    if (
      !isPlainObject(answer) ||
      typeof answer.name !== "string" ||
      !names.has(answer.name) ||
      seen.has(answer.name)
    )
      invalid("unexpected or duplicate answer name");
    seen.add(answer.name);
    const id = names.get(answer.name)!;
    const question = questions[id]!;
    if (answer.type === "refusal") {
      refusedIds.push(id);
      continue;
    }
    if (answer.type !== (question.type === "noul" ? "predicate" : question.type))
      invalid(`wrong type for ${id}`);
    if (question.type === "noul") {
      answers[id] = { type: "noul", noul: probability(answer.probability) };
      continue;
    }
    const labels =
      question.type === "choice"
        ? Object.keys(question.criteria)
        : question.criteria.map((_, i) => String(i));
    if (!Array.isArray(answer.probabilities)) invalid(`missing distribution for ${id}`);
    const probabilities: Record<string, number> = Object.create(null);
    for (const item of answer.probabilities) {
      if (!isPlainObject(item)) invalid("invalid distribution entry");
      const value = item.value;
      if (question.type === "score" && (typeof value !== "number" || !Number.isInteger(value)))
        invalid("invalid score level");
      const label = String(value);
      if (
        (question.type === "choice" && typeof value !== "string") ||
        !labels.includes(label) ||
        Object.hasOwn(probabilities, label)
      )
        invalid("unexpected or duplicate distribution entry");
      probabilities[label] = probability(item.probability);
    }
    if (Object.keys(probabilities).length !== labels.length) invalid("incomplete distribution");
    const confidence = probability(answer.confidence);
    if (question.type === "choice") {
      if (typeof answer.choice !== "string" || !labels.includes(answer.choice))
        invalid("invalid choice");
      answers[id] = { type: "choice", choice: answer.choice, confidence, probabilities };
    } else {
      if (
        typeof answer.score !== "number" ||
        !Number.isFinite(answer.score) ||
        answer.score < 0 ||
        answer.score > labels.length - 1
      )
        invalid("invalid score");
      answers[id] = {
        type: "score",
        score: answer.score,
        confidence,
        probabilities,
        legend: Object.fromEntries(
          question.criteria.map((description, i) => [String(i), description]),
        ),
      };
    }
  }
  if (seen.size !== ids.length) invalid("missing answers");
  if (refusedIds.length)
    throw new OpenAIDecisionsError(`Decisions refused questions: ${refusedIds.join(", ")}`, {
      kind: "refusal",
      refusedIds,
      body: raw,
    });
  return {
    model: raw.model,
    answers,
    usage: { input_tokens: usage.input_tokens, output_tokens: usage.output_tokens },
  } as SystemOneResult<Q>;
}

/** Internal validation shared by cache hits, merged results, and live decoding. */
export function validateNormalizedDecisionsResult<Q extends Questions>(
  raw: unknown,
  questions: Q,
): SystemOneResult<Q> {
  function invalid(): never {
    throw new OpenAIDecisionsError("Invalid normalized Decisions result", {
      kind: "response",
      body: raw,
    });
  }
  if (!isPlainObject(raw) || !isPlainObject(raw.answers)) invalid();
  const ids = Object.keys(questions);
  const answers = raw.answers;
  if (Object.keys(answers).length !== ids.length || ids.some((id) => !Object.hasOwn(answers, id)))
    invalid();
  const wire = ids.map((id, i) => {
    const answer = answers[id];
    const question = questions[id]!;
    if (!isPlainObject(answer) || answer.type !== question.type) invalid();
    const name = `q${i}`;
    if (question.type === "noul") return { type: "predicate", name, probability: answer.noul };
    if (!isPlainObject(answer.probabilities)) invalid();
    const probabilities = Object.entries(answer.probabilities).map(([value, probability]) => {
      if (question.type === "score" && !/^(0|[1-9][0-9]*)$/.test(value)) invalid();
      return { value: question.type === "score" ? Number(value) : value, probability };
    });
    if (question.type === "score") {
      const legend = Object.fromEntries(question.criteria.map((value, i) => [String(i), value]));
      if (!isJsonValue(answer.legend) || canonicalJson(answer.legend) !== canonicalJson(legend))
        invalid();
      return {
        type: "score",
        name,
        score: answer.score,
        confidence: answer.confidence,
        probabilities,
      };
    }
    return {
      type: "choice",
      name,
      choice: answer.choice,
      confidence: answer.confidence,
      probabilities,
    };
  });
  try {
    return decodeDecisionsResponse(
      { model: raw.model, usage: raw.usage, answers: wire },
      questions,
      ids,
    );
  } catch (error) {
    if (error instanceof OpenAIDecisionsError)
      throw new OpenAIDecisionsError(error.message, { kind: "response", body: raw });
    throw error;
  }
}

export function isValidDecisionsAnswer(question: unknown, answer: unknown): boolean {
  try {
    validateNormalizedDecisionsResult(
      { model: "cached", usage: { input_tokens: 0, output_tokens: 0 }, answers: { q: answer } },
      { q: question } as Questions,
    );
    return true;
  } catch {
    return false;
  }
}

export function normalizeDecisionsBaseURL(value = "https://api.openai.com/v1"): string {
  const normalized = value
    .trim()
    .replace(/\/+$/, "")
    .replace(/\/decisions$/, "");
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    return incompatible(
      "openai-base-url",
      "baseURL must be an HTTP(S) URL without credentials, query, or fragment",
    );
  }
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  )
    incompatible(
      "openai-base-url",
      "baseURL must be an HTTP(S) URL without credentials, query, or fragment",
    );
  return normalized;
}
