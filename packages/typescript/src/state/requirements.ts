import { type Diagnostic, diagnostic, SystemOnePromptsError } from "../definition/diagnostics.js";
import { locate, type SourceIndex } from "../definition/locate.js";
import { isJsonValue, isPlainObject, typeName } from "../json.js";
import { formatPath, getAtPath, type PathSegment, parsePath } from "./paths.js";

export const REQUIREMENT_TYPES = [
  "string",
  "number",
  "boolean",
  "array",
  "object",
  "null",
  "exists",
] as const;

export type RequirementType = (typeof REQUIREMENT_TYPES)[number];

/** `[requires]`: dotted / indexed state path → minimum runtime type. */
export type Requirements = Record<string, RequirementType>;

export type StateAssert<T = Record<string, unknown>> = (state: unknown) => asserts state is T;

export function parseRequirements(
  raw: unknown,
  index: SourceIndex,
): { requires: Requirements; diagnostics: Diagnostic[] } {
  const diagnostics: Diagnostic[] = [];
  const requires: Requirements = Object.create(null);
  if (raw == null) return { requires, diagnostics };
  if (!isPlainObject(raw)) {
    diagnostics.push(
      diagnostic(
        "error",
        "requires-not-table",
        "[requires] must be a table of path = type entries",
        locate(index, { table: "requires" }),
      ),
    );
    return { requires, diagnostics };
  }

  for (const [path, type] of Object.entries(raw as Record<string, unknown>)) {
    const loc = locate(index, { section: "requires", key: path, table: "requires" });
    const segments = parsePath(path);
    if (segments == null) {
      diagnostics.push(
        diagnostic(
          "error",
          "invalid-require-path",
          `invalid [requires] path \`${path}\``,
          loc,
          "use dotted identifiers and [n], [-n], or [] indexes, e.g. ticket.message or messages[-1].text",
        ),
      );
      continue;
    }
    if (!isRequirementType(type)) {
      diagnostics.push(
        diagnostic(
          "error",
          "invalid-require-type",
          `[requires] \`${path}\` has unknown type ${type == null ? "undefined" : `\`${String(type)}\``}`,
          loc,
          `expected ${REQUIREMENT_TYPES.join(" | ")}`,
        ),
      );
      continue;
    }
    requires[path] = type;
  }
  return { requires, diagnostics };
}

/**
 * Check both explicit types and containers implied by dotted/indexed descendants.
 * Compare parsed segments so spellings such as [0] and [00] refer to the same index.
 */
export function checkRequirementConflicts(
  requires: Requirements,
  index: SourceIndex,
): Diagnostic[] {
  const diagnostics: Diagnostic[] = [];
  const entries = Object.entries(requires).flatMap(([path, type]) => {
    const segments = parsePath(path);
    return segments ? [{ path, canonicalPath: formatPath(segments), type, segments }] : [];
  });
  const explicitTypes = new Set(
    entries.filter((entry) => entry.type !== "exists").map((entry) => entry.canonicalPath),
  );
  const reportedMixed = new Set<string>();

  for (let leftIndex = 0; leftIndex < entries.length; leftIndex += 1) {
    const left = entries[leftIndex]!;
    for (let rightIndex = leftIndex + 1; rightIndex < entries.length; rightIndex += 1) {
      const right = entries[rightIndex]!;
      const common = commonPrefixLength(left.segments, right.segments);
      const leftEnds = common === left.segments.length;
      const rightEnds = common === right.segments.length;

      if (leftEnds || rightEnds) {
        if (leftEnds && rightEnds) {
          if (!compatibleAtSamePath(left.type, right.type)) {
            diagnostics.push(
              diagnostic(
                "error",
                "require-conflict",
                `[requires] \`${left.path}\` is required as both \`${left.type}\` and \`${right.type}\``,
                locate(index, { section: "requires", key: left.path, table: "requires" }),
                "keep one compatible requirement for this path",
              ),
            );
          }
          continue;
        }

        const parent = leftEnds ? left : right;
        const child = leftEnds ? right : left;
        reportParentConflict(parent, child, child.segments[common]!, diagnostics, index);
        continue;
      }

      const leftNext = left.segments[common]!;
      const rightNext = right.segments[common]!;
      if (leftNext.kind === rightNext.kind) continue;

      const prefix = formatPath(left.segments.slice(0, common));
      // Explicit types are checked against each descendant by reportParentConflict.
      if (explicitTypes.has(prefix) || reportedMixed.has(prefix)) continue;
      reportedMixed.add(prefix);
      diagnostics.push(
        diagnostic(
          "error",
          "require-conflict",
          `[requires] \`${left.path}\` and \`${right.path}\` require \`${prefix}\` to be both an array and an object`,
          locate(index, { section: "requires", key: left.path, table: "requires" }),
          `use either dotted keys or [n] indexes under \`${prefix}\``,
        ),
      );
    }
  }
  return diagnostics;
}

function commonPrefixLength(left: readonly PathSegment[], right: readonly PathSegment[]): number {
  let length = 0;
  while (
    length < left.length &&
    length < right.length &&
    conflictSameSegment(left[length]!, right[length]!)
  ) {
    length += 1;
  }
  return length;
}

function sameSegment(left: PathSegment, right: PathSegment): boolean {
  if (left.kind === "key" && right.kind === "key") return left.name === right.name;
  if (left.kind === "index" && right.kind === "index") return left.index === right.index;
  return left.kind === "all" && right.kind === "all";
}

/** `[]` covers `[n]` for conflict analysis; distinct `[n]` indexes stay distinct. */
function conflictSameSegment(left: PathSegment, right: PathSegment): boolean {
  if (sameSegment(left, right)) return true;
  return impliesArray(left) && impliesArray(right) && (left.kind === "all" || right.kind === "all");
}

function impliesArray(segment: PathSegment): boolean {
  return segment.kind === "index" || segment.kind === "all";
}

function compatibleAtSamePath(left: RequirementType, right: RequirementType): boolean {
  return left === right || left === "exists" || right === "exists";
}

function reportParentConflict(
  parent: { path: string; type: RequirementType },
  child: { path: string },
  next: PathSegment,
  diagnostics: Diagnostic[],
  index: SourceIndex,
): void {
  if (parent.type === "exists") return;
  const container = impliesArray(next) ? "array" : "object";
  if (parent.type === container) return;

  const detail =
    parent.type === "object" || parent.type === "array"
      ? `requires it to be an ${container}`
      : "requires it to be a container";
  diagnostics.push(
    diagnostic(
      "error",
      "require-conflict",
      `[requires] \`${parent.path}\` is \`${parent.type}\` but \`${child.path}\` ${detail}`,
      locate(index, { section: "requires", key: parent.path, table: "requires" }),
      `change \`${parent.path}\` to "${container}" or "exists", or drop it`,
    ),
  );
}

export function isRequirementType(value: unknown): value is RequirementType {
  return typeof value === "string" && (REQUIREMENT_TYPES as readonly string[]).includes(value);
}

/**
 * Build an assertion that every `[requires]` path exists with the expected type.
 * The assertion narrows and throws; it never copies or reshapes the state.
 * Invalid paths fail here, at construction, rather than on first use.
 */
export function createStateAssert<T = Record<string, unknown>>(
  requires: Requirements,
): StateAssert<T> {
  const compiled: Array<{ path: string; expected: RequirementType; segments: PathSegment[] }> = [];
  for (const [path, expected] of Object.entries(requires)) {
    const segments = parsePath(path);
    if (!segments) {
      throw new SystemOnePromptsError(
        diagnostic("error", "invalid-require-path", `invalid [requires] path \`${path}\``),
      );
    }
    compiled.push({ path: formatPath(segments), expected, segments });
  }

  return (state: unknown): asserts state is T => {
    for (const { path, expected, segments } of compiled) {
      const error = assertSegments(state, segments, 0, path, expected);
      if (error) throw new SystemOnePromptsError(error);
    }
  };
}

/** Walk `segments` from `index`; `[]` checks every element and reports a non-array container. */
function assertSegments(
  current: unknown,
  segments: readonly PathSegment[],
  index: number,
  path: string,
  expected: RequirementType,
): Diagnostic | undefined {
  if (index === segments.length) return checkRequirement(path, expected, current);
  const head = segments[index]!;
  if (head.kind === "all") {
    if (!Array.isArray(current)) {
      return checkRequirement(formatPath(segments.slice(0, index)), "array", current);
    }
    for (const element of current) {
      const error = assertSegments(element, segments, index + 1, path, expected);
      if (error) return error;
    }
    return undefined;
  }
  return assertSegments(getAtPath(current, [head]), segments, index + 1, path, expected);
}

export function checkRequirement(
  path: string,
  expected: RequirementType,
  actual: unknown,
): Diagnostic | undefined {
  if (matchesType(expected, actual)) return undefined;
  const got = actual === undefined ? "undefined" : typeName(actual);
  return diagnostic("error", "state-requirement", `${path}: expected ${expected}, got ${got}`);
}

function matchesType(expected: RequirementType, actual: unknown): boolean {
  switch (expected) {
    case "string":
      return typeof actual === "string";
    case "number":
      return typeof actual === "number" && Number.isFinite(actual);
    case "boolean":
      return typeof actual === "boolean";
    case "array":
      return Array.isArray(actual) && isJsonValue(actual);
    case "object":
      return isPlainObject(actual) && isJsonValue(actual);
    case "null":
      return actual === null;
    case "exists":
      return actual !== undefined;
  }
}
