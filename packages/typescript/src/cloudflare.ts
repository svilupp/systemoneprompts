import type { Fetch } from "./native.js";

export const CLOUDFLARE_MODEL = "typesafe/jev";
export const CLOUDFLARE_API_ORIGIN = "https://api.cloudflare.com";
const SYSTEM_ONE_PATH = "/v1/systemone";

export function cloudflareRunUrl(accountId: string): string {
  return `${CLOUDFLARE_API_ORIGIN}/client/v4/accounts/${encodeURIComponent(accountId)}/ai/run`;
}

export function wrapCloudflareRequest(payload: { state: unknown; questions: unknown }): {
  model: string;
  input: { state: unknown; questions: unknown };
} {
  return {
    model: CLOUDFLARE_MODEL,
    input: { state: payload.state, questions: payload.questions },
  };
}

/** True when `fetch` is `createCachingFetch()` so Cloudflare wrapping stays innermost. */
export function isCachingFetch(fetch: Fetch): boolean {
  return (
    typeof (fetch as { stats?: unknown }).stats === "function" &&
    typeof (fetch as { dir?: unknown }).dir === "string"
  );
}

export function markCloudflareFetch<T extends Fetch>(fetch: T): T {
  (fetch as T & { systemonepromptsCloudflare: boolean }).systemonepromptsCloudflare = true;
  return fetch;
}

export function isCloudflareFetch(fetch: Fetch): boolean {
  return (fetch as { systemonepromptsCloudflare?: unknown }).systemonepromptsCloudflare === true;
}

export function cloudflareErrorMessage(body: unknown): string | undefined {
  if (!body || typeof body !== "object") return undefined;
  const errors = (body as { errors?: unknown }).errors;
  if (!Array.isArray(errors) || errors.length === 0) return undefined;
  const first = errors[0];
  if (
    first &&
    typeof first === "object" &&
    typeof (first as { message?: unknown }).message === "string"
  ) {
    const message = (first as { message: string }).message.trim();
    return message === "" ? undefined : message;
  }
  return undefined;
}

export function cloudflareFailureStatus(body: unknown, httpStatus?: number): number | undefined {
  if (!body || typeof body !== "object") return undefined;
  const record = body as { success?: unknown; result?: unknown; errors?: unknown };
  if (record.success === false) {
    if (httpStatus !== undefined && (httpStatus < 200 || httpStatus >= 300)) return httpStatus;
    const errors = record.errors;
    if (Array.isArray(errors) && errors[0] && typeof errors[0] === "object") {
      const code = (errors[0] as { code?: unknown }).code;
      if (code === 2021) return 402;
    }
    return 400;
  }
  const state =
    record.result && typeof record.result === "object"
      ? (record.result as { state?: unknown }).state
      : undefined;
  if (typeof state === "string" && state !== "Completed") return 502;
  return undefined;
}

/** Pull `{ model, answers, usage }` out of a Cloudflare Workers AI envelope.
 * Already-native System One objects are returned unchanged.
 */
export function unwrapCloudflareResult(parsed: unknown): Record<string, unknown> | undefined {
  if (!isRecord(parsed)) return undefined;
  if (isRecord(parsed.answers)) return parsed;
  const outer = parsed.result;
  if (!isRecord(outer)) return undefined;
  if (isRecord(outer.answers)) return outer;
  const inner = outer.result;
  if (isRecord(inner) && isRecord(inner.answers)) return inner;
  return undefined;
}

export function createCloudflareFetch(options: { accountId: string; fetch?: Fetch }): Fetch {
  const accountId = options.accountId.trim();
  const inner: Fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
  const fetch: Fetch = async (input, init) => {
    if (!isSystemOnePost(input, init) || typeof init?.body !== "string") {
      return inner(input, init);
    }
    let payload: { state?: unknown; questions?: unknown };
    try {
      payload = JSON.parse(init.body) as { state?: unknown; questions?: unknown };
    } catch {
      return inner(input, init);
    }
    if (payload.questions == null || typeof payload.questions !== "object") {
      return inner(input, init);
    }
    const headers = new Headers(init.headers);
    headers.delete("content-length");
    headers.delete("host");
    headers.delete("content-encoding");
    headers.delete("transfer-encoding");
    headers.set("content-type", "application/json");
    const response = await inner(cloudflareRunUrl(accountId), {
      ...init,
      method: "POST",
      headers,
      body: JSON.stringify(
        wrapCloudflareRequest({ state: payload.state, questions: payload.questions }),
      ),
    });
    const parsed = await parseJsonBody(response);
    const failure = cloudflareFailureStatus(parsed, response.status);
    if (failure !== undefined) {
      return jsonCopy(parsed, failure, response);
    }
    if (!response.ok) return jsonCopy(parsed, response.status, response);
    const unwrapped = unwrapCloudflareResult(parsed);
    if (unwrapped === undefined) return jsonCopy(parsed, 502, response);
    return jsonCopy(unwrapped, 200, response);
  };
  return markCloudflareFetch(fetch);
}

function isSystemOnePost(input: string, init?: RequestInit): boolean {
  if ((init?.method ?? "POST").toUpperCase() !== "POST") return false;
  try {
    return new URL(input).pathname.endsWith(SYSTEM_ONE_PATH);
  } catch {
    return input.includes(SYSTEM_ONE_PATH);
  }
}

async function parseJsonBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text.length === 0) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function jsonCopy(body: unknown, status: number, source: Response): Response {
  const headers = new Headers(source.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("transfer-encoding");
  headers.set("content-type", "application/json");
  return new Response(body === undefined ? "" : JSON.stringify(body), {
    status,
    statusText: source.statusText,
    headers,
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}
