export type DiagnosticSeverity = "error" | "warning";

export interface SourceLocation {
  filename?: string;
  line?: number;
  column?: number;
}

export interface Diagnostic extends SourceLocation {
  severity: DiagnosticSeverity;
  code: string;
  message: string;
  hint?: string;
}

/**
 * Thrown when a definition, state, or answer set is unusable.
 * `diagnostic` is the primary problem; `diagnostics` lists every error that was found.
 */
export class SystemOnePromptsError extends Error {
  readonly diagnostic: Diagnostic;
  readonly diagnostics: readonly Diagnostic[];

  constructor(diagnostics: Diagnostic | readonly Diagnostic[]) {
    const list = Array.isArray(diagnostics) ? diagnostics : [diagnostics as Diagnostic];
    if (list.length === 0) {
      throw new TypeError("SystemOnePromptsError requires at least one diagnostic");
    }
    super(list.map(formatDiagnostic).join("\n"));
    this.name = "SystemOnePromptsError";
    this.diagnostic = list[0]!;
    this.diagnostics = list;
  }
}

export function formatDiagnostic(d: Diagnostic): string {
  const where = formatLocation(d);
  const head = where ? `${where}  ${d.message}` : d.message;
  if (!d.hint) return head;
  const indent = where ? " ".repeat(where.length + 2) : "  ";
  return `${head}\n${indent}${d.hint}`;
}

export function formatLocation(loc: SourceLocation): string {
  if (!loc.filename && loc.line == null) return "";
  const file = loc.filename ?? "<input>";
  if (loc.line == null) return file;
  if (loc.column == null) return `${file}:${loc.line}`;
  return `${file}:${loc.line}:${loc.column}`;
}

export function diagnostic(
  severity: DiagnosticSeverity,
  code: string,
  message: string,
  loc: SourceLocation = {},
  hint?: string,
): Diagnostic {
  return { severity, code, message, hint, ...loc };
}

export function hasErrors(diagnostics: readonly Diagnostic[]): boolean {
  return diagnostics.some((d) => d.severity === "error");
}

export function errorsOf(diagnostics: readonly Diagnostic[]): Diagnostic[] {
  return diagnostics.filter((d) => d.severity === "error");
}

/** Closest candidate by edit distance, or `undefined` when nothing is plausibly a typo. */
export function nearestMatch(needle: string, candidates: readonly string[]): string | undefined {
  let best: string | undefined;
  let bestScore = Number.POSITIVE_INFINITY;
  for (const candidate of candidates) {
    const score = levenshtein(needle, candidate);
    if (score < bestScore) {
      best = candidate;
      bestScore = score;
    }
  }
  if (best == null) return undefined;
  const threshold = Math.max(2, Math.ceil(needle.length * 0.4));
  return bestScore <= threshold ? best : undefined;
}

function levenshtein(a: string, b: string): number {
  let previous = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const current = [i];
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      current[j] = Math.min(previous[j]! + 1, current[j - 1]! + 1, previous[j - 1]! + cost);
    }
    previous = current;
  }
  return previous[b.length]!;
}
