import { type Diagnostic, diagnostic, nearestMatch } from "../definition/diagnostics.js";
import { locate, type SourceIndex } from "../definition/locate.js";
import type { Questions } from "../native.js";
import { formatPath, type PathSegment, parsePath } from "../state/paths.js";
import type { Requirements } from "../state/requirements.js";

const BACKTICK_RE = /`([^`]+)`/g;

/**
 * Warn when a backticked, path-shaped token in `instructions` / `criteria` is not
 * guaranteed by `[requires]`. A prefix of a guaranteed path (`ticket` when
 * `ticket.message` is required) counts as guaranteed.
 */
export function lintBackticks(
  questions: Questions,
  requires: Requirements,
  index: SourceIndex,
): Diagnostic[] {
  const guaranteed = Object.keys(requires).flatMap((path) => {
    const segments = parsePath(path);
    return segments ? [{ formatted: formatPath(segments), segments }] : [];
  });
  const diagnostics: Diagnostic[] = [];
  const guaranteedPaths = guaranteed.map((entry) => entry.formatted);

  for (const [id, question] of Object.entries(questions)) {
    const loc = locate(index, { table: ["questions", id], section: "questions", key: id });
    for (const token of collectBackticks(question.instructions, question.criteria)) {
      const segments = parsePath(token);
      if (!segments) continue;
      if (guaranteed.some((entry) => pathGuaranteesToken(entry.segments, segments))) continue;
      const suggestion = nearestMatch(token, guaranteedPaths);
      diagnostics.push(
        diagnostic(
          "warning",
          "unguaranteed-backtick",
          `\`${token}\` is not guaranteed by [requires]`,
          loc,
          suggestion ? `did you mean \`${suggestion}\`?` : undefined,
        ),
      );
    }
  }

  return diagnostics;
}

function pathGuaranteesToken(
  required: readonly PathSegment[],
  token: readonly PathSegment[],
): boolean {
  for (let i = 0; i < token.length; i += 1) {
    const requiredSegment = required[i];
    if (requiredSegment == null) return false;
    if (!segmentGuarantees(requiredSegment, token[i]!)) return false;
  }
  return true;
}

function segmentGuarantees(required: PathSegment, token: PathSegment): boolean {
  if (required.kind === "key" && token.kind === "key") return required.name === token.name;
  if (required.kind === "index" && token.kind === "index") return required.index === token.index;
  if (required.kind === "all" && token.kind === "all") return true;
  return required.kind === "all" && token.kind === "index";
}

export function collectBackticks(...values: unknown[]): string[] {
  const found: string[] = [];
  walk(values, (text) => {
    for (const match of text.matchAll(BACKTICK_RE)) {
      const token = match[1] ?? "";
      if (token && !found.includes(token)) found.push(token);
    }
  });
  return found;
}

function walk(value: unknown, onString: (text: string) => void): void {
  if (typeof value === "string") {
    onString(value);
    return;
  }
  if (Array.isArray(value)) {
    for (const entry of value) walk(entry, onString);
    return;
  }
  if (value && typeof value === "object") {
    for (const entry of Object.values(value)) walk(entry, onString);
  }
}
