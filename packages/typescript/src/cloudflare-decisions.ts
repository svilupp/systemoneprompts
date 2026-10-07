import type { SystemOneCallOptions } from "./client.js";
import { isCachingFetch } from "./cloudflare.js";
import {
  CloudflareDecisionsError,
  decodeDecisionsResponse,
  encodeDecisionsRequest,
  incompatible,
  modelName,
  normalizeDecisionsBaseURL,
} from "./cloudflare-decisions-codec.js";
import type { Fetch, Questions, SystemOneRequest, SystemOneResult } from "./native.js";
import type { SystemOneClient } from "./patterns/index.js";

export { CloudflareDecisionsError } from "./cloudflare-decisions-codec.js";
export interface CloudflareDecisionsClientOptions {
  apiKey?: string;
  baseURL?: string;
  accountId?: string;
  defaultModel?: string;
  fetch?: Fetch;
  timeout?: number;
  maxRetries?: number;
  headers?: Record<string, string>;
}

export class CloudflareDecisionsClient implements SystemOneClient {
  readonly baseURL: string;
  readonly accountId: string;
  readonly defaultModel: string;
  readonly timeout: number;
  readonly maxRetries: number;
  readonly fetch: Fetch;
  readonly defaultHeaders: Readonly<Record<string, string>>;
  readonly #apiKey: string;
  constructor(options: CloudflareDecisionsClientOptions = {}) {
    this.defaultModel = modelName(
      options.defaultModel === undefined ? "clef" : options.defaultModel,
    );
    this.#apiKey = options.apiKey?.trim() || process.env.CLOUDFLARE_API_TOKEN?.trim() || "";
    if (!this.#apiKey)
      incompatible(
        "missing-credentials",
        "CLOUDFLARE_API_TOKEN is not set. Pass apiKey or export CLOUDFLARE_API_TOKEN.",
      );
    this.accountId = options.accountId?.trim() || process.env.CLOUDFLARE_ACCOUNT_ID?.trim() || "";
    if (!this.accountId)
      incompatible(
        "missing-account",
        "CLOUDFLARE_ACCOUNT_ID is not set. Pass accountId or export CLOUDFLARE_ACCOUNT_ID.",
      );
    this.baseURL = normalizeDecisionsBaseURL(options.baseURL, this.accountId);
    this.timeout = options.timeout ?? 10_000;
    this.maxRetries = options.maxRetries ?? 2;
    if (
      !Number.isFinite(this.timeout) ||
      this.timeout <= 0 ||
      !Number.isInteger(this.maxRetries) ||
      this.maxRetries < 0
    )
      incompatible(
        "cloudflare-options",
        "timeout must be positive and maxRetries a nonnegative integer",
      );
    this.fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
    if (isCachingFetch(this.fetch))
      incompatible(
        "cloudflare-cache-transport",
        "Use createCachedCloudflareDecisionsClient instead of passing a caching fetch as raw network I/O",
      );
    this.defaultHeaders = { ...options.headers };
  }
  async systemOne<const Q extends Questions>(
    request: SystemOneRequest<Q>,
    options: SystemOneCallOptions = {},
  ): Promise<SystemOneResult<Q>> {
    // Snapshot before the first await: normalization uses the exact rubric sent.
    const { body, ids } = encodeDecisionsRequest(
      request.state,
      request.questions,
      request.model === undefined ? this.defaultModel : request.model,
    );
    const questions = structuredClone(request.questions);
    const payload = JSON.stringify(body);
    const timeout = options.timeout ?? this.timeout;
    if (!Number.isFinite(timeout) || timeout <= 0)
      incompatible("cloudflare-options", "timeout must be positive");
    const headers = new Headers({ ...this.defaultHeaders, ...options.headers });
    headers.set("Authorization", `Bearer ${this.#apiKey}`);
    headers.set("Content-Type", "application/json");
    headers.set("Accept", "application/json");
    let raw: unknown;
    let requestId: string | undefined;
    for (let attempt = 0; ; attempt++) {
      if (options.signal?.aborted)
        throw new CloudflareDecisionsError("Decisions request aborted", { kind: "transport" });
      const controller = new AbortController();
      const abort = () => controller.abort(options.signal?.reason);
      options.signal?.addEventListener("abort", abort, { once: true });
      let timedOut = false;
      const timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, timeout);
      let retryAfter: number | undefined;
      try {
        const response = await this.fetch(`${this.baseURL}/@cf/cloudflare/${body.model}`, {
          method: "POST",
          headers,
          body: payload,
          signal: controller.signal,
        });
        requestId =
          response.headers.get("cf-ray") ?? response.headers.get("x-request-id") ?? undefined;
        const text = await response.text();
        try {
          raw = JSON.parse(text);
        } catch {
          raw = text;
        }
        if (timedOut)
          throw new CloudflareDecisionsError("Decisions request timed out", { kind: "timeout" });
        if (options.signal?.aborted)
          throw new CloudflareDecisionsError("Decisions request aborted", { kind: "transport" });
        if (
          response.ok &&
          !(raw && typeof raw === "object" && (raw as { success?: unknown }).success === false)
        )
          break;
        const status = response.ok ? 400 : response.status;
        retryAfter = retrySeconds(response.headers);
        const error = new CloudflareDecisionsError(
          `Cloudflare Decisions HTTP ${status}${requestId ? ` (request ${requestId})` : ""}`,
          { kind: "http", status: status, body: raw, requestId, retryAfter },
        );
        if (
          attempt >= this.maxRetries ||
          !(status === 408 || status === 429 || (status >= 500 && status < 600))
        )
          throw error;
      } catch (error) {
        if (options.signal?.aborted)
          throw new CloudflareDecisionsError("Decisions request aborted", {
            kind: "transport",
            body: error,
          });
        if (error instanceof CloudflareDecisionsError && error.kind !== "timeout") throw error;
        if (
          attempt >= this.maxRetries ||
          !(timedOut || error instanceof TypeError || error instanceof CloudflareDecisionsError)
        )
          throw error instanceof CloudflareDecisionsError
            ? error
            : new CloudflareDecisionsError(
                timedOut ? "Decisions request timed out" : "Decisions connection failed",
                { kind: timedOut ? "timeout" : "transport", body: error },
              );
      } finally {
        clearTimeout(timer);
        options.signal?.removeEventListener("abort", abort);
      }
      await delay(
        retryAfter === undefined ? Math.min(500 * 2 ** attempt, 5000) : retryAfter * 1000,
        options.signal,
      );
    }
    try {
      return decodeDecisionsResponse(raw, questions, ids);
    } catch (error) {
      if (error instanceof CloudflareDecisionsError)
        throw new CloudflareDecisionsError(error.message, {
          kind: error.kind,
          body: raw,
          requestId,
        });
      throw error;
    }
  }
}
function retrySeconds(headers: Headers): number | undefined {
  const ms = Number(headers.get("retry-after-ms"));
  if (headers.has("retry-after-ms") && Number.isFinite(ms) && ms >= 0 && ms <= 60000)
    return ms / 1000;
  const raw = headers.get("retry-after");
  if (raw === null) return undefined;
  const seconds = Number(raw);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds, 60);
  const date = Date.parse(raw);
  return Number.isFinite(date) ? Math.min(60, Math.max(0, (date - Date.now()) / 1000)) : undefined;
}
function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const finish = () => {
      signal?.removeEventListener("abort", abort);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    const abort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(new CloudflareDecisionsError("Decisions request aborted", { kind: "transport" }));
    };
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
  });
}
