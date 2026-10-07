import { indexSource } from "./definition/locate.js";
import { canonicalJson, isJsonValue, isPlainObject } from "./json.js";
import type { Questions, SystemOneResult } from "./native.js";
import { validateQuestions } from "./questions/schema.js";

export class CloudflareDecisionsError extends Error {
  readonly kind: "http" | "transport" | "timeout" | "response" | "compatibility";
  readonly body: unknown;
  readonly status?: number;
  readonly requestId?: string;
  readonly retryAfter?: number;
  readonly code?: string;
  constructor(
    message: string,
    details: {
      kind: CloudflareDecisionsError["kind"];
      body?: unknown;
      status?: number;
      requestId?: string;
      retryAfter?: number;
      code?: string;
    },
  ) {
    super(message);
    this.name = "CloudflareDecisionsError";
    this.kind = details.kind;
    this.body = details.body;
    this.status = details.status;
    this.requestId = details.requestId;
    this.retryAfter = details.retryAfter;
    this.code = details.code;
  }
}

export function incompatible(code: string, message: string): never {
  throw new CloudflareDecisionsError(`${code}: ${message}`, { kind: "compatibility", code });
}
export function modelName(value: unknown): string {
  if (typeof value !== "string")
    incompatible("cloudflare-model", "model must be clef or clef-flash");
  const model = value.trim().replace(/^@cf\/cloudflare\//, "");
  if (model !== "clef" && model !== "clef-flash")
    incompatible("cloudflare-model", "model must be clef or clef-flash");
  return model;
}
export function normalizeDecisionsBaseURL(value: string | undefined, accountId: string): string {
  const normalized = (
    value ?? `https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(accountId)}/ai/run`
  )
    .trim()
    .replace(/\/+$/, "");
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    return incompatible(
      "cloudflare-base-url",
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
      "cloudflare-base-url",
      "baseURL must be an HTTP(S) URL without credentials, query, or fragment",
    );
  return normalized;
}

export function encodeDecisionsRequest(state: unknown, questions: Questions, model: string) {
  if (!isJsonValue(state)) incompatible("cloudflare-state-json", "state must be JSON-compatible");
  const checked = validateQuestions(questions, indexSource(""));
  const errors = checked.diagnostics.filter((d) => d.severity === "error");
  if (errors.length) incompatible(errors[0]!.code, errors.map((d) => d.message).join("; "));
  const ids = Object.keys(questions);
  if (ids.length > 64)
    incompatible("cloudflare-question-limit", "at most 64 questions are supported");
  const empty = (value: unknown): boolean =>
    value == null ||
    (typeof value === "string" && !value.trim()) ||
    (typeof value === "object" && Object.keys(value).length === 0);
  const wire = ids.map((id, i) => {
    const question = checked.questions[id]!;
    if (question.type === "choice" && Object.keys(question.criteria).length < 2)
      incompatible("cloudflare-choice-min-options", `question ${id} needs at least two options`);
    if (question.type === "score" && question.criteria.length > 10)
      incompatible("cloudflare-score-max-levels", `question ${id} allows at most ten levels`);
    if (
      question.type === "noul" &&
      empty(question.instructions) &&
      Object.values(question.criteria ?? {}).every(empty)
    )
      incompatible(
        "cloudflare-question-empty",
        `question ${id} needs instructions or outcome criteria`,
      );
    return [
      `q${i}`,
      {
        ...question,
        instructions: empty(question.instructions)
          ? "Evaluate the supplied evidence against the criteria."
          : question.instructions,
      },
    ];
  });
  return {
    body: {
      model: modelName(model),
      state,
      questions: Object.fromEntries(wire),
    },
    ids,
  };
}

export function validateNormalizedDecisionsResult<Q extends Questions>(
  raw: unknown,
  questions: Q,
): SystemOneResult<Q> {
  function invalid(): never {
    throw new CloudflareDecisionsError("Invalid Cloudflare Decisions response", {
      kind: "response",
      body: raw,
    });
  }
  if (
    !isPlainObject(raw) ||
    typeof raw.model !== "string" ||
    !raw.model.trim() ||
    !isPlainObject(raw.answers) ||
    !isPlainObject(raw.usage)
  )
    invalid();
  const answers = raw.answers;
  const usage = raw.usage;
  if (Object.keys(answers).length !== Object.keys(questions).length) invalid();
  for (const key of ["input_tokens", "output_tokens"]) {
    const n = usage[key];
    if (typeof n !== "number" || !Number.isInteger(n) || n < 0) invalid();
  }
  const probability = (value: unknown) =>
    typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
  for (const [id, question] of Object.entries(questions)) {
    if (!Object.hasOwn(answers, id)) invalid();
    const answer = answers[id];
    if (!isPlainObject(answer) || answer.type !== question.type) invalid();
    if (question.type === "noul") {
      if (!probability(answer.noul)) invalid();
      continue;
    }
    const labels =
      question.type === "choice"
        ? Object.keys(question.criteria)
        : question.criteria.map((_, i) => String(i));
    if (!probability(answer.confidence) || !isPlainObject(answer.probabilities)) invalid();
    const probabilities = answer.probabilities;
    if (
      Object.keys(probabilities).length !== labels.length ||
      labels.some(
        (label) => !Object.hasOwn(probabilities, label) || !probability(probabilities[label]),
      )
    )
      invalid();
    if (question.type === "choice") {
      if (typeof answer.choice !== "string" || !labels.includes(answer.choice)) invalid();
    } else {
      if (
        typeof answer.score !== "number" ||
        !Number.isFinite(answer.score) ||
        answer.score < 0 ||
        answer.score > labels.length - 1
      )
        invalid();
      const legend = Object.fromEntries(question.criteria.map((v, i) => [String(i), v]));
      if (!isJsonValue(answer.legend) || canonicalJson(answer.legend) !== canonicalJson(legend))
        invalid();
    }
  }
  return raw as unknown as SystemOneResult<Q>;
}

export function decodeDecisionsResponse<Q extends Questions>(
  raw: unknown,
  questions: Q,
  ids: string[],
): SystemOneResult<Q> {
  const result = isPlainObject(raw) && isPlainObject(raw.result) ? raw.result : raw;
  if (!isPlainObject(result) || !isPlainObject(result.answers))
    throw new CloudflareDecisionsError("Invalid Cloudflare Decisions envelope", {
      kind: "response",
      body: raw,
    });
  const answers = result.answers;
  const wireQuestions = Object.fromEntries(
    ids.map((id, i) => [`q${i}`, questions[id]!]),
  ) as Questions;
  validateNormalizedDecisionsResult(result, wireQuestions);
  return {
    ...result,
    answers: Object.fromEntries(ids.map((id, i) => [id, answers[`q${i}`]])),
  } as unknown as SystemOneResult<Q>;
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
