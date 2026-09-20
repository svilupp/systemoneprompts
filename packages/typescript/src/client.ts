import { DEFAULT_MODEL } from "./model.js";
import type { Fetch, Questions, SystemOneRequest, SystemOneResult } from "./native.js";

export const DEFAULT_BASE_URL = "https://api.typesafe.ai";
export const DEFAULT_TIMEOUT_MS = 10_000;
const SYSTEM_ONE_PATH = "/v1/systemone";
const CLIENT_VERSION = "0.1.0";
const DEFAULT_MAX_RETRIES = 2;
function isRetryStatus(status: number): boolean {
  return status === 408 || status === 429 || (status >= 500 && status < 600);
}

export class TypeSafeClientError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "TypeSafeClientError";
  }
}

export class TypeSafeHttpError extends TypeSafeClientError {
  readonly status: number;
  readonly body: unknown;
  readonly requestId: string | undefined;
  readonly retryAfter: number | undefined;

  constructor(
    status: number,
    body: unknown,
    requestId: string | undefined,
    message?: string,
    retryAfter?: number,
  ) {
    super(message ?? `TypeSafe API error ${status}`, { cause: body });
    this.name = "TypeSafeHttpError";
    this.status = status;
    this.body = body;
    this.requestId = requestId;
    this.retryAfter = retryAfter;
  }
}

export class TypeSafeRateLimitError extends TypeSafeHttpError {
  constructor(
    status: number,
    body: unknown,
    requestId: string | undefined,
    message?: string,
    retryAfter?: number,
  ) {
    super(status, body, requestId, message, retryAfter);
    this.name = "TypeSafeRateLimitError";
  }
}

export class TypeSafeTimeoutError extends TypeSafeClientError {
  readonly timeoutMs: number;

  constructor(timeoutMs: number, options?: ErrorOptions) {
    super(`TypeSafe API timed out after ${timeoutMs}ms`, options);
    this.name = "TypeSafeTimeoutError";
    this.timeoutMs = timeoutMs;
  }
}

export interface TypeSafeClientOptions {
  /** Falls back to `TYPESAFE_API_KEY`. */
  apiKey?: string;
  /** Falls back to `TYPESAFE_BASE_URL`, then `https://api.typesafe.ai`. */
  baseURL?: string;
  /** Falls back to `TYPESAFE_DEFAULT_MODEL`, then `jev-latest`. */
  defaultModel?: string;
  /** Inject fetch for tests, cache, or a wrapper with its own timeouts. */
  fetch?: Fetch;
  /** Per-attempt timeout in milliseconds. Default 10000. */
  timeout?: number;
  /** Extra headers merged onto every request. */
  headers?: Record<string, string>;
  /** Retries after the first attempt. Default 2. Set 0 to disable. */
  maxRetries?: number;
}

export interface SystemOneCallOptions {
  signal?: AbortSignal;
  timeout?: number;
  headers?: Record<string, string>;
}

/**
 * Native HTTP client for TypeSafe System One / JEV.
 *
 * Pass `fetch` (or `timeout`) when you need different transport behaviour. Patterns
 * accept any object with a compatible `systemOne`.
 */
export class TypeSafeClient {
  readonly baseURL: string;
  readonly defaultModel: string;
  readonly timeout: number;
  readonly fetch: Fetch;
  readonly maxRetries: number;
  readonly defaultHeaders: Readonly<Record<string, string>>;
  readonly #apiKey: string;

  constructor(options: TypeSafeClientOptions = {}) {
    this.#apiKey = trimEnv(options.apiKey) ?? trimEnv(process.env.TYPESAFE_API_KEY) ?? "";
    if (!this.#apiKey) {
      throw new TypeSafeClientError(
        "TYPESAFE_API_KEY is not set. Pass apiKey or export TYPESAFE_API_KEY.",
      );
    }
    this.baseURL = stripSlash(
      trimEnv(options.baseURL) ?? trimEnv(process.env.TYPESAFE_BASE_URL) ?? DEFAULT_BASE_URL,
    );
    this.defaultModel =
      trimEnv(options.defaultModel) ?? trimEnv(process.env.TYPESAFE_DEFAULT_MODEL) ?? DEFAULT_MODEL;
    this.timeout = positiveMs("timeout", options.timeout ?? DEFAULT_TIMEOUT_MS);
    this.maxRetries = nonNegativeInt("maxRetries", options.maxRetries ?? DEFAULT_MAX_RETRIES);
    this.fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
    if (typeof this.fetch !== "function") {
      throw new TypeSafeClientError("No fetch is available. Pass fetch to TypeSafeClient.");
    }
    this.defaultHeaders = { ...(options.headers ?? {}) };
  }

  async systemOne<const Q extends Questions>(
    request: SystemOneRequest<Q>,
    options: SystemOneCallOptions = {},
  ): Promise<SystemOneResult<Q>> {
    const questions = request.questions;
    if (questions == null || Object.keys(questions).length === 0) {
      throw new TypeSafeClientError("systemOne requires at least one question");
    }
    const body = {
      state: request.state,
      questions,
      model: request.model ?? this.defaultModel,
    };
    const parsed = await this.#postJson(SYSTEM_ONE_PATH, body, options);
    return parsed as SystemOneResult<Q>;
  }

  async #postJson(path: string, body: unknown, options: SystemOneCallOptions): Promise<unknown> {
    const timeout =
      options.timeout === undefined ? this.timeout : positiveMs("timeout", options.timeout);
    const url = `${this.baseURL}${path}`;
    const owned: Record<string, string> = {
      Authorization: `Bearer ${this.#apiKey}`,
      Accept: "application/json",
      "Content-Type": "application/json",
      "User-Agent": `systemoneprompts/${CLIENT_VERSION}`,
    };
    // Header names are case-insensitive; a caller `authorization` must not merge with ours.
    const ownedNames = new Set(Object.keys(owned).map((name) => name.toLowerCase()));
    const headers: Record<string, string> = {};
    for (const [name, value] of Object.entries({ ...this.defaultHeaders, ...options.headers })) {
      if (!ownedNames.has(name.toLowerCase())) headers[name] = value;
    }
    Object.assign(headers, owned);
    const payload = JSON.stringify(body);
    let lastError: unknown;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        const { response, parsed } = await this.#attempt(
          url,
          headers,
          payload,
          timeout,
          options.signal,
        );
        const requestId = response.headers.get("x-typesafe-request-id") ?? undefined;
        if (response.ok) return parsed;
        const ErrorType = response.status === 429 ? TypeSafeRateLimitError : TypeSafeHttpError;
        const error = new ErrorType(
          response.status,
          parsed,
          requestId,
          describeHttpError(response.status, parsed, requestId),
          retryAfterSeconds(response.headers),
        );
        if (attempt >= this.maxRetries || !isRetryStatus(response.status)) throw error;
        lastError = error;
        await sleep(retryDelayMs(attempt, response.headers), options.signal);
      } catch (error) {
        if (error instanceof TypeSafeHttpError) throw error;
        if (error instanceof TypeSafeTimeoutError) {
          if (attempt >= this.maxRetries) throw error;
          lastError = error;
          await sleep(retryDelayMs(attempt), options.signal);
          continue;
        }
        if (options.signal?.aborted) {
          throw new TypeSafeClientError("TypeSafe API request was aborted", { cause: error });
        }
        // A fetch wrapper (e.g. the dev cache's `CacheMissError`) already produced a client
        // error; surface it unchanged instead of wrapping and retrying it as a network failure.
        if (error instanceof TypeSafeClientError) throw error;
        if (attempt >= this.maxRetries) {
          throw new TypeSafeClientError(
            error instanceof Error
              ? `TypeSafe API connection error: ${error.message}`
              : "TypeSafe API connection error",
            { cause: error },
          );
        }
        lastError = error;
        await sleep(retryDelayMs(attempt), options.signal);
      }
    }
    throw lastError instanceof Error
      ? lastError
      : new TypeSafeClientError("TypeSafe API request failed");
  }

  async #attempt(
    url: string,
    headers: Record<string, string>,
    body: string,
    timeout: number,
    signal?: AbortSignal,
  ): Promise<{ response: Response; parsed: unknown }> {
    const controller = new AbortController();
    const abortFromCaller = () => controller.abort(signal?.reason);
    if (signal?.aborted) abortFromCaller();
    signal?.addEventListener("abort", abortFromCaller, { once: true });
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeout);
    try {
      const response = await this.fetch(url, {
        method: "POST",
        headers,
        body,
        signal: controller.signal,
      });
      const parsed = await parseBody(response);
      if (timedOut) throw new TypeSafeTimeoutError(timeout);
      return { response, parsed };
    } catch (error) {
      if (signal?.aborted) throw error;
      if (timedOut) throw new TypeSafeTimeoutError(timeout, { cause: error });
      throw error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abortFromCaller);
    }
  }
}

function trimEnv(value: string | undefined): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed === "" ? undefined : trimmed;
}

function stripSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function positiveMs(name: string, value: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    throw new TypeSafeClientError(`${name} must be a positive number of milliseconds`);
  }
  return value;
}

function nonNegativeInt(name: string, value: number): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new TypeSafeClientError(`${name} must be a non-negative integer`);
  }
  return value;
}

function retryAfterSeconds(headers: Headers): number | undefined {
  const ms = Number(headers.get("retry-after-ms"));
  if (headers.has("retry-after-ms") && Number.isFinite(ms) && ms >= 0 && ms <= 60_000) {
    return ms / 1000;
  }
  const raw = headers.get("retry-after");
  if (raw === null) return undefined;
  const seconds = Number(raw);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds, 60);
  const date = Date.parse(raw);
  if (Number.isFinite(date)) {
    const delay = date - Date.now();
    if (delay <= 0) return 0;
    return Math.min(delay, 60_000) / 1000;
  }
  return undefined;
}

function retryDelayMs(attempt: number, headers?: Headers): number {
  if (headers) {
    const seconds = retryAfterSeconds(headers);
    if (seconds !== undefined) return Math.min(seconds * 1000, 60_000);
  }
  const exponential = Math.min(500 * 2 ** attempt, 5000);
  return Math.round(exponential * (1 - Math.random() * 0.25));
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text.length === 0) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function describeHttpError(status: number, body: unknown, requestId: string | undefined): string {
  const id = requestId ? ` (request ${requestId})` : "";
  if (typeof body === "string" && body.trim())
    return `TypeSafe API error ${status}${id}: ${body.trim()}`;
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    const message =
      (typeof record.error === "string" && record.error) ||
      (typeof record.message === "string" && record.message) ||
      (record.error &&
        typeof record.error === "object" &&
        typeof (record.error as { message?: unknown }).message === "string" &&
        (record.error as { message: string }).message);
    if (message) return `TypeSafe API error ${status}${id}: ${message}`;
  }
  return `TypeSafe API error ${status}${id}`;
}
