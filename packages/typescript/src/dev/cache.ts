import { createHash, randomUUID } from "node:crypto";
import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import { isAnswerForQuestion, isAnswerShape } from "../answers.js";
import { TypeSafeClientError } from "../client.js";
import { canonicalJson, isPlainObject } from "../json.js";
import type { Fetch } from "../native.js";

export type CacheMode = "read-write" | "read-only" | "refresh";

export interface CachingFetchOptions {
  dir?: string;
  mode?: CacheMode;
  fetch?: Fetch;
  /** Provider-specific validation; invalid entries become misses. */
  validateEntry?: (question: unknown, answer: unknown) => boolean;
}

/** Cumulative counts since the fetch was created; `keys` are the question ids of the last request. */
export interface CacheStats {
  requests: number;
  hits: number;
  misses: number;
  keys: string[];
}

export interface CachedEntry {
  hash: string;
  requestedModel?: string;
  reportedModel: string;
  answer: unknown;
}

export interface CachingFetch extends Fetch {
  stats(): CacheStats;
  readonly dir: string;
}

/** Read-only miss. A `TypeSafeClientError` so `TypeSafeClient` surfaces it without retrying. */
export class CacheMissError extends TypeSafeClientError {
  readonly ids: string[];

  constructor(ids: string[]) {
    super(`cache miss in read-only mode: ${ids.map((id) => `\`${id}\``).join(", ")}`);
    this.name = "CacheMissError";
    this.ids = ids;
  }
}

const SYSTEMONE_PATH = "/v1/systemone";

export function defaultCacheDir(cwd = process.cwd()): string {
  return join(cwd, ".systemoneprompts", "cache");
}

/**
 * A `fetch` for `new TypeSafeClient({ fetch })` that caches System One answers per
 * `(model, id, state, question)`. `id` is required so two questions with identical
 * bodies cannot share an entry. `state` is the request state as sent; callers that
 * need inspect-isolation send separate requests. A request is split into cached hits
 * and a smaller live request for the misses; the merged response reports only the
 * tokens actually spent. Non-System-One traffic passes through.
 */
export function createCachingFetch(opts: CachingFetchOptions = {}): CachingFetch {
  const dir = opts.dir ?? defaultCacheDir();
  const mode = opts.mode ?? "read-write";
  const baseFetch: Fetch = opts.fetch ?? globalThis.fetch;
  const stats: CacheStats = { requests: 0, hits: 0, misses: 0, keys: [] };

  const cachingFetch: CachingFetch = (async (input: string, init?: RequestInit) => {
    if (!isSystemOneRequest(input, init) || typeof init?.body !== "string") {
      return baseFetch(input, init);
    }
    let payload: Record<string, unknown>;
    try {
      const parsed = JSON.parse(init.body);
      if (!isPlainObject(parsed)) return baseFetch(input, init);
      payload = parsed;
    } catch {
      return baseFetch(input, init);
    }
    if (!isPlainObject(payload.questions)) {
      return baseFetch(input, init);
    }

    const model = typeof payload.model === "string" ? payload.model : undefined;
    const state = payload.state;
    const questions = payload.questions;
    const ids = Object.keys(questions);
    const hits = dictionary<CachedEntry>();
    const misses = dictionary<unknown>();

    for (const id of ids) {
      const question = questions[id];
      const hash = questionHash({ model, id, state, question });
      if (mode === "refresh") {
        misses[id] = question;
        continue;
      }
      const cached = await readEntry(dir, hash, question);
      if (cached && (!opts.validateEntry || opts.validateEntry(question, cached.answer))) {
        hits[id] = cached;
      } else {
        misses[id] = question;
      }
    }

    const missIds = Object.keys(misses);
    stats.requests += 1;
    stats.hits += ids.length - missIds.length;
    stats.misses += missIds.length;
    stats.keys = ids;

    if (missIds.length === 0) {
      return jsonResponse({
        model: firstReportedModel(hits) ?? model ?? "jev-latest",
        answers: Object.fromEntries(ids.map((id) => [id, hits[id]!.answer])),
        usage: { input_tokens: 0, output_tokens: 0 },
      });
    }

    if (mode === "read-only") {
      throw new CacheMissError(missIds);
    }

    const response = await baseFetch(input, {
      ...init,
      headers: withoutContentLength(init.headers),
      body: JSON.stringify({ ...payload, questions: misses }),
    });
    // Hand errors back untouched so TypeSafeClient sees the real status, headers, and body.
    if (!response.ok) return response;

    let result: Record<string, unknown> | undefined;
    let answers: Record<string, unknown> | undefined;
    try {
      const parsed = await response.clone().json();
      if (isPlainObject(parsed)) {
        result = parsed;
        if (isPlainObject(parsed.answers)) answers = parsed.answers;
      }
    } catch {
      // A cached hit still makes it possible to return a useful merged response.
    }

    const validLiveAnswers = dictionary<unknown>();
    if (answers) {
      for (const id of missIds) {
        if (
          Object.hasOwn(answers, id) &&
          isAnswerForQuestion(misses[id], answers[id]) &&
          (!opts.validateEntry || opts.validateEntry(misses[id], answers[id]))
        ) {
          validLiveAnswers[id] = answers[id];
        }
      }
    }

    const allMissesValid = missIds.every((id) => Object.hasOwn(validLiveAnswers, id));
    const hitIds = Object.keys(hits);
    if (!allMissesValid && hitIds.length === 0) return response;

    const reportedModel =
      (result && typeof result.model === "string" ? result.model : undefined) ??
      firstReportedModel(hits) ??
      model ??
      "jev-latest";
    for (const id of Object.keys(validLiveAnswers)) {
      const hash = questionHash({ model, id, state, question: misses[id] });
      const entry: CachedEntry = {
        hash,
        requestedModel: model,
        reportedModel,
        answer: validLiveAnswers[id],
      };
      await writeEntry(dir, hash, entry);
      hits[id] = entry;
    }

    const usage =
      result && isPlainObject(result.usage) ? result.usage : { input_tokens: 0, output_tokens: 0 };
    const mergedAnswers = dictionary<unknown>();
    for (const id of ids) {
      if (hits[id]) mergedAnswers[id] = hits[id].answer;
      else if (Object.hasOwn(validLiveAnswers, id)) mergedAnswers[id] = validLiveAnswers[id];
    }
    return jsonResponse(
      {
        model: reportedModel,
        answers: mergedAnswers,
        usage,
      },
      response.status,
      response.statusText,
      response.headers,
    );
  }) as CachingFetch;

  cachingFetch.stats = () => ({ ...stats, keys: [...stats.keys] });
  Object.defineProperty(cachingFetch, "dir", { value: dir });
  if ((baseFetch as { systemonepromptsCloudflare?: unknown }).systemonepromptsCloudflare === true) {
    (
      cachingFetch as CachingFetch & { systemonepromptsCloudflare: boolean }
    ).systemonepromptsCloudflare = true;
  }
  return cachingFetch;
}

/** Cache key: sha256 of the canonical JSON of `{ model, id, state, question }`. */
export function questionHash(parts: {
  model?: string;
  id?: string;
  state: unknown;
  question: unknown;
}): string {
  const payload: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(parts)) {
    if (key === "model" && value == null) continue;
    if (key === "id" && value == null) continue;
    payload[key] = value;
  }
  return createHash("sha256").update(canonicalJson(payload)).digest("hex");
}

export async function cacheStats(dir = defaultCacheDir()): Promise<{
  entries: number;
  models: Record<string, number>;
  drift: Array<{ requested?: string; reported: string; count: number }>;
}> {
  const files = await listEntries(dir);
  const models = dictionary<number>();
  const driftMap = new Map<string, { requested?: string; reported: string; count: number }>();
  let entries = 0;
  for (const file of files) {
    const hash = basename(file, ".json");
    const raw = await readEntryFile(file, hash);
    if (!raw) continue;
    entries += 1;
    const reported = raw.reportedModel;
    models[reported] = (models[reported] ?? 0) + 1;
    const key = JSON.stringify([raw.requestedModel ?? null, reported]);
    const existing = driftMap.get(key) ?? { requested: raw.requestedModel, reported, count: 0 };
    existing.count += 1;
    driftMap.set(key, existing);
  }
  return { entries, models, drift: [...driftMap.values()] };
}

export async function clearCache(dir = defaultCacheDir()): Promise<void> {
  await rm(dir, { recursive: true, force: true });
}

async function readEntry(
  dir: string,
  hash: string,
  question: unknown,
): Promise<CachedEntry | undefined> {
  return readEntryFile(entryPath(dir, hash), hash, question);
}

async function writeEntry(dir: string, hash: string, entry: CachedEntry): Promise<void> {
  const path = entryPath(dir, hash);
  await mkdir(dirname(path), { recursive: true });
  const temporaryPath = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporaryPath, `${JSON.stringify(entry, null, 2)}\n`);
    await rename(temporaryPath, path);
  } finally {
    await rm(temporaryPath, { force: true }).catch(() => undefined);
  }
}

function entryPath(dir: string, hash: string): string {
  return join(dir, hash.slice(0, 2), `${hash}.json`);
}

async function listEntries(dir: string): Promise<string[]> {
  try {
    await stat(dir);
    const out: string[] = [];
    const shards = await readdir(dir, { withFileTypes: true });
    for (const shard of shards) {
      if (!shard.isDirectory()) continue;
      const files = await readdir(join(dir, shard.name));
      for (const file of files) {
        if (file.endsWith(".json")) out.push(join(dir, shard.name, file));
      }
    }
    return out;
  } catch {
    return [];
  }
}

function isSystemOneRequest(input: string, init?: RequestInit): boolean {
  try {
    const url = new URL(input);
    if (!url.pathname.endsWith(SYSTEMONE_PATH)) return false;
  } catch {
    if (!input.includes(SYSTEMONE_PATH)) return false;
  }
  return (init?.method ?? "GET").toUpperCase() === "POST";
}

function withoutContentLength(headers: RequestInit["headers"]): Headers {
  const next = new Headers(headers);
  next.delete("content-length");
  return next;
}

function jsonResponse(
  body: unknown,
  status = 200,
  statusText = "OK",
  headers?: ConstructorParameters<typeof Headers>[0],
): Response {
  const responseHeaders = new Headers(headers);
  responseHeaders.delete("content-length");
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("transfer-encoding");
  if (!responseHeaders.has("content-type")) responseHeaders.set("content-type", "application/json");
  return new Response(JSON.stringify(body), {
    status,
    statusText,
    headers: responseHeaders,
  });
}

function firstReportedModel(hits: Record<string, CachedEntry>): string | undefined {
  for (const entry of Object.values(hits)) {
    if (entry.reportedModel) return entry.reportedModel;
  }
  return undefined;
}

function dictionary<T>(): Record<string, T> {
  return Object.create(null) as Record<string, T>;
}

function readEntryFile(
  file: string,
  hash: string,
  question?: unknown,
): Promise<CachedEntry | undefined> {
  return readFile(file, "utf8")
    .then((raw) => JSON.parse(raw) as unknown)
    .then((value) => (isCachedEntry(value, hash, question) ? value : undefined))
    .catch(() => undefined);
}

function isCachedEntry(value: unknown, hash: string, question?: unknown): value is CachedEntry {
  if (!/^[0-9a-f]{64}$/.test(hash)) return false;
  if (!isPlainObject(value) || value.hash !== hash) return false;
  if (typeof value.reportedModel !== "string" || value.reportedModel.length === 0) return false;
  if (Object.hasOwn(value, "requestedModel") && typeof value.requestedModel !== "string")
    return false;
  return (
    Object.hasOwn(value, "answer") &&
    isAnswerShape(value.answer) &&
    (question === undefined || isAnswerForQuestion(question, value.answer))
  );
}
