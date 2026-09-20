import type { FactorDef, FactorTable } from "../factors/schema.js";
import type { JsonValue, Questions } from "../native.js";
import type { Requirements } from "../state/requirements.js";
import type { Diagnostic } from "./diagnostics.js";
import type { SourceIndex } from "./locate.js";

export const KNOWN_TOP_LEVEL = [
  "title",
  "version",
  "description",
  "model",
  "requires",
  "questions",
  "factors",
  "data",
] as const;

/** Verbatim `[factors]` tables, keyed by factor id — the input to `createFactorEvaluator`. */
export type FactorDefinitions = Record<string, FactorTable>;

/** Application-owned JSON-compatible data from the optional `[data]` table. */
export type DefinitionData = Record<string, JsonValue>;

export interface DefinitionMeta {
  title?: string;
  version?: string;
  description?: string;
  [key: string]: string | number | boolean | undefined;
}

export interface DefinitionSource {
  filename?: string;
  text: string;
  index: SourceIndex;
}

export interface Definition {
  meta: DefinitionMeta;
  /** TOML `model` pin; `undefined` lets the JEV default (or `TYPESAFE_DEFAULT_MODEL`) apply. */
  model?: string;
  requires: Requirements;
  /** Native TypeSafe/JEV question objects. */
  questions: Questions;
  /** Parsed factor definitions, normalised into operator / predicate nodes. */
  factors: Record<string, FactorDef>;
  /** Verbatim factor tables; pass to `createFactorEvaluator`. */
  factorDefinitions: FactorDefinitions;
  /** Application-owned JSON-compatible data; systemoneprompts does not interpret it. */
  data: DefinitionData;
  /** Structural problems found while parsing (bad types, unknown fields, malformed questions). */
  diagnostics: Diagnostic[];
  source: DefinitionSource;
}
