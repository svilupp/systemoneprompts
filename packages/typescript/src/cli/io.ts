import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { TypeSafeClient } from "../client.js";
import { createCloudflareFetch } from "../cloudflare.js";
import { CloudflareDecisionsClient } from "../cloudflare-decisions.js";
import { checkDefinition } from "../definition/check.js";
import { type Diagnostic, formatDiagnostic, hasErrors } from "../definition/diagnostics.js";
import { parseDefinition } from "../definition/parse.js";
import type { Definition } from "../definition/schema.js";
import { type CachingFetch, createCachingFetch } from "../dev/cache.js";
import { createCachedCloudflareDecisionsClient } from "../dev/cloudflare-cache.js";
import { createCachedOpenAIDecisionsClient } from "../dev/openai-cache.js";
import { readEnvModel, resolveModel } from "../model.js";
import { OpenAIDecisionsClient } from "../openai-decisions.js";
import { openRouterBaseURL, openRouterCacheDir } from "../openrouter.js";
import type { SystemOneClient } from "../patterns/index.js";
import { loadDotEnv } from "./env.js";

export async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

export async function readText(path: string): Promise<string> {
  return readFile(path, "utf8");
}

/** Parse JSON with a message that names the source instead of a bare "Unexpected token". */
export function parseJson(text: string, what: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch (error) {
    fail(`${what}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/** Parse and check a definition file; print diagnostics and exit on errors. */
export async function loadChecked(file: string): Promise<Definition> {
  const source = await readText(file);
  const def = parseDefinition(source, { filename: file });
  const diagnostics = checkDefinition(def);
  printDiagnostics(diagnostics);
  if (hasErrors(diagnostics)) {
    process.exit(1);
  }
  return def;
}

/**
 * Select a client from CLI override, TOML provider, then TypeSafe.
 * OpenAI uses its own default model and credentials. TypeSafe model precedence:
 * default → `TYPESAFE_DEFAULT_MODEL` / `TYPESAFE_MODEL` → TOML `model` → `--model`.
 *
 * Cloudflare mode (`CLOUDFLARE_ACCOUNT_ID`) uses `CLOUDFLARE_API_TOKEN` and is
 * mutually exclusive with `TYPESAFE_BASE_URL`.
 */
export function createClient(
  def: Definition,
  options: {
    cache?: boolean;
    model?: string;
    provider?: string;
    cacheRoot?: string;
    baseURL?: string;
  },
): { client: SystemOneClient; model: string; cache?: CachingFetch } {
  loadDotEnv();
  const provider = options.provider ?? def.provider ?? "typesafe";
  if (
    provider !== "typesafe" &&
    provider !== "openai" &&
    provider !== "cloudflare" &&
    provider !== "openrouter"
  )
    fail('provider-value: provider must be "typesafe", "openai", "cloudflare", or "openrouter"');
  const baseURL = options.baseURL ?? def.baseURL;
  if (provider === "openrouter") {
    const endpoint = openRouterBaseURL(baseURL);
    const model = resolveModel("~typesafe/jev-latest", def.model, options.model);
    const cache = options.cache
      ? createCachingFetch({
          dir: openRouterCacheDir({ dir: options.cacheRoot, baseURL: endpoint }),
        })
      : undefined;
    const client = new TypeSafeClient({
      provider: "openrouter",
      baseURL: endpoint,
      defaultModel: model,
      ...(cache ? { fetch: cache } : {}),
    });
    return { client, model, cache };
  }
  if (provider === "cloudflare") {
    if (options.model !== undefined && !options.model.trim())
      fail("cloudflare-model: model must be nonblank");
    const network = new CloudflareDecisionsClient({
      baseURL,
      defaultModel: resolveModel("clef", def.model, options.model),
    });
    const model = network.defaultModel;
    return options.cache
      ? {
          ...createCachedCloudflareDecisionsClient({ client: network, dir: options.cacheRoot }),
          model,
        }
      : { client: network, model };
  }
  if (provider === "openai") {
    if (options.model !== undefined && !options.model.trim())
      fail("openai-model-empty: model must be nonblank");
    const model = resolveModel("gpt-6-luna", def.model, options.model);
    const network = new OpenAIDecisionsClient({ defaultModel: model, baseURL });
    return options.cache
      ? { ...createCachedOpenAIDecisionsClient({ client: network, dir: options.cacheRoot }), model }
      : { client: network, model };
  }
  const model = resolveModel(readEnvModel(), def.model, options.model);
  const cloudflareAccountId = process.env.CLOUDFLARE_ACCOUNT_ID?.trim() || undefined;
  try {
    const cache = options.cache
      ? createCachingFetch({
          ...(cloudflareAccountId
            ? { fetch: createCloudflareFetch({ accountId: cloudflareAccountId }) }
            : {}),
          ...(options.cacheRoot ? { dir: join(options.cacheRoot, "cache") } : {}),
        })
      : undefined;
    const client = new TypeSafeClient({
      baseURL,
      ...(cache ? { fetch: cache } : {}),
      ...(cloudflareAccountId ? { cloudflareAccountId } : {}),
      defaultModel: model,
    });
    return { client, model, cache };
  } catch (error) {
    fail(error instanceof Error ? error.message : String(error));
  }
}

export function printDiagnostics(diagnostics: readonly Diagnostic[], strict = false): number {
  let errors = 0;
  let warnings = 0;
  for (const d of diagnostics) {
    const severity = strict && d.severity === "warning" ? "error" : d.severity;
    if (severity === "error") errors += 1;
    else warnings += 1;
    console.error(`${severity}: ${formatDiagnostic({ ...d, severity })}`);
  }
  if (diagnostics.length > 0) {
    console.error(`${errors} error(s), ${warnings} warning(s)`);
  }
  return errors;
}

export function fail(message: string, code = 1): never {
  console.error(message);
  process.exit(code);
}
