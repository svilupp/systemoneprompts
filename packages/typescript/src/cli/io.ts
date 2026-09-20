import { readFile } from "node:fs/promises";
import { TypeSafeClient } from "../client.js";
import { checkDefinition } from "../definition/check.js";
import { type Diagnostic, formatDiagnostic, hasErrors } from "../definition/diagnostics.js";
import { parseDefinition } from "../definition/parse.js";
import type { Definition } from "../definition/schema.js";
import { type CachingFetch, createCachingFetch } from "../dev/cache.js";
import { readEnvModel, resolveModel } from "../model.js";
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
 * Build the TypeSafe client for a live CLI call. Model precedence, later wins:
 * default → `TYPESAFE_DEFAULT_MODEL` / `TYPESAFE_MODEL` → TOML `model` → `--model`.
 */
export function createClient(
  def: Definition,
  options: { cache?: boolean; model?: string },
): { client: TypeSafeClient; model: string; cache?: CachingFetch } {
  loadDotEnv();
  const cache = options.cache ? createCachingFetch() : undefined;
  const model = resolveModel(readEnvModel(), def.model, options.model);
  try {
    const client = new TypeSafeClient({ ...(cache ? { fetch: cache } : {}), defaultModel: model });
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
