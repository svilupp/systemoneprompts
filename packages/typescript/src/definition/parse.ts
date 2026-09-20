import { readFile } from "node:fs/promises";
import { parse as parseToml, TomlError } from "smol-toml";
import { parseFactors } from "../factors/schema.js";
import { isJsonValue, isPlainObject } from "../json.js";
import { validateQuestions } from "../questions/schema.js";
import { parseRequirements } from "../state/requirements.js";
import { type Diagnostic, diagnostic, nearestMatch, SystemOnePromptsError } from "./diagnostics.js";
import { indexSource, locate } from "./locate.js";
import {
  type Definition,
  type DefinitionData,
  type DefinitionMeta,
  KNOWN_TOP_LEVEL,
} from "./schema.js";

export interface ParseOptions {
  filename?: string;
}

const META_KEYS = ["title", "version", "description"] as const;
const KNOWN_TABLES = ["requires", "questions", "factors", "data"] as const;

/**
 * Parse a TOML definition into native TypeSafe objects.
 *
 * Throws `SystemOnePromptsError` only when the TOML itself is invalid. Structural problems
 * (bad field types, malformed questions, unknown factor fields) are collected in
 * `definition.diagnostics`; the offending entries are omitted from the result.
 * Run `checkDefinition` for cross-cutting checks (references, cycles, lint).
 */
export function parseDefinition(source: string, opts: ParseOptions = {}): Definition {
  const filename = opts.filename;
  let raw: unknown;
  try {
    raw = parseToml(source);
  } catch (error) {
    throw wrapTomlError(error, filename);
  }
  if (!isPlainObject(raw)) {
    throw new SystemOnePromptsError(
      diagnostic("error", "toml-root", "definition must be a TOML table", { filename, line: 1 }),
    );
  }

  const index = indexSource(source, filename);
  const diagnostics: Diagnostic[] = [];
  const meta: DefinitionMeta = Object.create(null);

  const parsedData = parseData(raw.data, index);
  diagnostics.push(...parsedData.diagnostics);

  for (const key of META_KEYS) {
    const value = raw[key];
    if (value === undefined) continue;
    if (typeof value === "string") meta[key] = value;
    else {
      diagnostics.push(
        diagnostic("error", "meta-string", `\`${key}\` must be a string`, locate(index, { key })),
      );
    }
  }

  let model: string | undefined;
  if (raw.model !== undefined) {
    if (typeof raw.model === "string" && raw.model.trim() !== "") model = raw.model.trim();
    else {
      diagnostics.push(
        diagnostic(
          "error",
          "model-string",
          "`model` must be a non-empty string",
          locate(index, { key: "model" }),
        ),
      );
    }
  }

  for (const [key, value] of Object.entries(raw)) {
    if ((KNOWN_TOP_LEVEL as readonly string[]).includes(key)) continue;
    if (isPlainObject(value) || Array.isArray(value)) {
      const suggestion = nearestMatch(key, KNOWN_TABLES);
      diagnostics.push(
        diagnostic(
          "warning",
          "unknown-table",
          `unknown top-level table [${key}]`,
          locate(index, { table: key, key }),
          suggestion ? `did you mean [${suggestion}]?` : undefined,
        ),
      );
      continue;
    }
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      meta[key] = value;
    }
  }

  const requires = parseRequirements(raw.requires, index);
  diagnostics.push(...requires.diagnostics);

  const questions = validateQuestions(raw.questions, index);
  diagnostics.push(...questions.diagnostics);

  const factors = parseFactors(raw.factors, new Set(Object.keys(questions.questions)), index);
  diagnostics.push(...factors.diagnostics);

  return {
    meta,
    model,
    requires: requires.requires,
    questions: questions.questions,
    factors: factors.factors,
    factorDefinitions: factors.factorDefinitions,
    data: parsedData.data,
    diagnostics,
    source: { filename, text: source, index },
  };
}

export async function loadDefinition(path: string): Promise<Definition> {
  const text = await readFile(path, "utf8");
  return parseDefinition(text, { filename: path });
}

function wrapTomlError(error: unknown, filename?: string): SystemOnePromptsError {
  if (error instanceof TomlError) {
    const line = "line" in error && typeof error.line === "number" ? error.line : undefined;
    const column = "column" in error && typeof error.column === "number" ? error.column : undefined;
    return new SystemOnePromptsError(
      diagnostic("error", "toml-syntax", error.message, { filename, line, column }),
    );
  }
  const message = error instanceof Error ? error.message : "failed to parse TOML";
  return new SystemOnePromptsError(diagnostic("error", "toml-syntax", message, { filename }));
}

interface ParsedData {
  data: DefinitionData;
  diagnostics: Diagnostic[];
}

/**
 * Parse the application-owned data namespace. The root is deliberately a
 * table, while all descendants are only constrained by the JSON value rules.
 * Invalid trees are discarded as a unit so callers cannot accidentally use a
 * partially valid application configuration.
 */
function parseData(raw: unknown, index: ReturnType<typeof indexSource>): ParsedData {
  const empty = (): DefinitionData => Object.create(null) as DefinitionData;
  if (raw === undefined) return { data: empty(), diagnostics: [] };

  if (!isPlainObject(raw)) {
    return {
      data: empty(),
      diagnostics: [
        diagnostic(
          "error",
          "data-type",
          "`data` must be a TOML table",
          locate(index, { table: "data", key: "data" }),
        ),
      ],
    };
  }

  if (isJsonValue(raw)) return { data: raw as DefinitionData, diagnostics: [] };

  const invalid = findInvalidJson(raw, ["data"]);
  const path = invalid?.path ?? ["data"];
  return {
    data: empty(),
    diagnostics: [
      diagnostic(
        "error",
        "data-json",
        `\`data\` contains a non-JSON-compatible value at ${formatDataPath(path)}`,
        locateDataPath(index, path),
      ),
    ],
  };
}

interface InvalidJsonPath {
  path: string[];
}

function findInvalidJson(value: unknown, path: string[]): InvalidJsonPath | undefined {
  if (value === null || typeof value === "string" || typeof value === "boolean") return undefined;
  if (typeof value === "number") return Number.isFinite(value) ? undefined : { path };
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      if (!(index in value)) return { path: [...path, `[${index}]`] };
      const invalid = findInvalidJson(value[index], [...path, `[${index}]`]);
      if (invalid) return invalid;
    }
    return undefined;
  }
  if (!isPlainObject(value)) return { path };
  for (const [key, child] of Object.entries(value)) {
    const invalid = findInvalidJson(child, [...path, key]);
    if (invalid) return invalid;
  }
  return undefined;
}

function locateDataPath(index: ReturnType<typeof indexSource>, path: readonly string[]) {
  const serialized = JSON.stringify(path);
  const location = index.keyPaths?.get(serialized) ?? index.tablePaths?.get(serialized);
  return location ?? locate(index, { table: "data", key: "data" });
}

function formatDataPath(path: readonly string[]): string {
  let result = "";
  for (const segment of path) {
    if (segment.startsWith("[")) result += segment;
    else if (result === "") result = segment;
    else if (/^[A-Za-z0-9_-]+$/.test(segment)) result += `.${segment}`;
    else result += `[${JSON.stringify(segment)}]`;
  }
  return `\`${result}\``;
}
