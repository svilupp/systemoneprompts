import type { SourceLocation } from "./diagnostics.js";

export interface SourceIndex {
  filename?: string;
  tables: Map<string, SourceLocation>;
  keys: Map<string, SourceLocation>;
  /** Structural paths preserve dots inside quoted TOML keys. */
  tablePaths?: Map<string, SourceLocation>;
  keyPaths?: Map<string, SourceLocation>;
}

// Capture the optional second bracket separately so `[[table]]` keeps `table`.
// The lazy path also lets quoted keys contain a closing bracket.
const TABLE_RE = /^(\s*)\[(\[?)(.*?)(\]?)](?:\s*#.*)?$/;
const KEY_RE = /^(\s*)((?:"(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_-]+))\s*=/;

export function indexSource(text: string, filename?: string): SourceIndex {
  const tables = new Map<string, SourceLocation>();
  const keys = new Map<string, SourceLocation>();
  const tablePaths = new Map<string, SourceLocation>();
  const keyPaths = new Map<string, SourceLocation>();
  const lines = text.split(/\r?\n/);
  let currentTable = "";
  let currentTablePath: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? "";
    const trimmed = line.trim();
    if (trimmed === "" || trimmed.startsWith("#")) continue;

    const tableMatch = TABLE_RE.exec(line);
    if (tableMatch) {
      const rawPath = (tableMatch[3] ?? "").trim();
      const segments = parseTomlPath(rawPath);
      const path = segments ? normalizeTablePath(segments) : rawPath;
      const loc: SourceLocation = {
        filename,
        line: i + 1,
        column: (tableMatch[1]?.length ?? 0) + 1,
      };
      if (!tables.has(path)) tables.set(path, loc);
      if (segments && !tablePaths.has(pathKey(segments))) {
        tablePaths.set(pathKey(segments), loc);
      }
      currentTable = path;
      currentTablePath = segments ?? [];
      continue;
    }

    const keyMatch = KEY_RE.exec(line);
    if (keyMatch) {
      const rawKey = keyMatch[2] ?? "";
      const key = unquoteTomlKey(rawKey);
      const qualified = currentTable ? `${currentTable}.${key}` : key;
      const loc: SourceLocation = {
        filename,
        line: i + 1,
        column: (keyMatch[1]?.length ?? 0) + 1,
      };
      if (!keys.has(qualified)) keys.set(qualified, loc);
      if (!keys.has(key)) keys.set(key, loc);
      const qualifiedPath = [...currentTablePath, key];
      if (!keyPaths.has(pathKey(qualifiedPath))) keyPaths.set(pathKey(qualifiedPath), loc);
      if (!keyPaths.has(pathKey([key]))) keyPaths.set(pathKey([key]), loc);
    }
  }

  return { filename, tables, keys, tablePaths, keyPaths };
}

/** An index with no positions; `locate` against it yields empty locations. */
export const EMPTY_INDEX: SourceIndex = {
  tables: new Map(),
  keys: new Map(),
  tablePaths: new Map(),
  keyPaths: new Map(),
};

/**
 * Best-effort source position, most specific first: a `key` inside `section`
 * (`"ticket.message" = …` under `[requires]`), then a `table` header
 * (`[questions.topic]`), then a bare key, then the section header.
 */
export function locate(
  index: SourceIndex,
  options: { table?: string | readonly string[]; key?: string; section?: string },
): SourceLocation {
  const filename = index.filename;
  if (options.section && options.key) {
    const scopedTable = index.tablePaths?.get(pathKey([options.section, options.key]));
    if (scopedTable) return scopedTable;
    const nestedTable = findNestedTable(index.tablePaths, [options.section, options.key]);
    if (nestedTable) return nestedTable;
    const scoped = index.keyPaths?.get(pathKey([options.section, options.key]));
    if (scoped) return scoped;
    const loc = index.keys.get(`${options.section}.${options.key}`);
    if (loc) return loc;
  }
  if (options.table) {
    const table = options.table;
    const segments = typeof table === "string" ? parseTomlPath(table) : table;
    const loc = segments ? index.tablePaths?.get(pathKey(segments)) : undefined;
    if (loc) return loc;
    // A nested array-of-tables field can represent a path without its own header.
    const nested = segments ? findNestedTable(index.tablePaths, segments) : undefined;
    if (nested) return nested;
    const legacy = typeof table === "string" ? table : table.join(".");
    const fallback = index.tables.get(legacy);
    if (fallback) return fallback;
  }
  if (options.key) {
    const loc = index.keyPaths?.get(pathKey([options.key]));
    if (loc) return loc;
    const fallback = index.keys.get(options.key);
    if (fallback) return fallback;
  }
  if (options.section) {
    const loc = index.tablePaths?.get(pathKey([options.section]));
    if (loc) return loc;
    const fallback = index.tables.get(options.section);
    if (fallback) return fallback;
  }
  return { filename };
}

function normalizeTablePath(segments: readonly string[]): string {
  return segments.join(".");
}

function pathKey(segments: readonly string[]): string {
  return JSON.stringify(segments);
}

function findNestedTable(
  tablePaths: Map<string, SourceLocation> | undefined,
  segments: readonly string[],
): SourceLocation | undefined {
  if (!tablePaths) return undefined;
  for (const [serialized, loc] of tablePaths) {
    let candidate: unknown;
    try {
      candidate = JSON.parse(serialized);
    } catch {
      continue;
    }
    if (
      Array.isArray(candidate) &&
      candidate.length > segments.length &&
      segments.every((segment, index) => candidate[index] === segment)
    ) {
      return loc;
    }
  }
  return undefined;
}

/** Parse a TOML dotted key path without treating dots in quoted keys as separators. */
function parseTomlPath(raw: string): string[] | null {
  const segments: string[] = [];
  let cursor = 0;

  while (cursor < raw.length) {
    while (raw[cursor] === " ") cursor += 1;
    if (cursor >= raw.length) break;

    if (raw[cursor] === '"' || raw[cursor] === "'") {
      const quote = raw[cursor]!;
      const start = cursor;
      cursor += 1;
      let escaped = false;
      while (cursor < raw.length) {
        const char = raw[cursor]!;
        cursor += 1;
        if (escaped) {
          escaped = false;
        } else if (quote === '"' && char === "\\") {
          escaped = true;
        } else if (char === quote) {
          break;
        }
      }
      const token = raw.slice(start, cursor);
      if (!token.endsWith(quote)) return null;
      segments.push(unquoteTomlKey(token));
    } else {
      const start = cursor;
      while (cursor < raw.length && raw[cursor] !== ".") cursor += 1;
      const token = raw.slice(start, cursor).trim();
      if (!token) return null;
      segments.push(token);
    }

    while (raw[cursor] === " ") cursor += 1;
    if (cursor >= raw.length) break;
    if (raw[cursor] !== ".") return null;
    cursor += 1;
  }

  return segments.length > 0 ? segments : null;
}

function unquoteTomlKey(raw: string): string {
  if (raw.startsWith('"') && raw.endsWith('"')) {
    try {
      return JSON.parse(raw) as string;
    } catch {
      return raw.slice(1, -1);
    }
  }
  if (raw.startsWith("'") && raw.endsWith("'")) {
    return raw.slice(1, -1);
  }
  return raw;
}
