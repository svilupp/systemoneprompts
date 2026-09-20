export type PathSegment =
  | { kind: "key"; name: string }
  | { kind: "index"; index: number }
  | { kind: "all" };

const IDENT = "[A-Za-z_][A-Za-z0-9_]*";
const INDEX = "\\[(\\d+)\\]";
const ALL = "\\[\\]";
const PATH_RE = new RegExp(`^(${IDENT})((?:\\.${IDENT}|${INDEX}|${ALL})*)$`);
const TAIL_RE = new RegExp(`\\.(${IDENT})|${INDEX}|${ALL}`, "g");
const MAX_INDEX = 2 ** 32 - 2;

export function parsePath(path: string): PathSegment[] | null {
  const match = PATH_RE.exec(path);
  if (!match) return null;
  const segments: PathSegment[] = [{ kind: "key", name: match[1] ?? "" }];
  const tail = match[2] ?? "";
  if (!tail) return segments;
  for (const part of tail.matchAll(TAIL_RE)) {
    if (part[1] != null) segments.push({ kind: "key", name: part[1] });
    else if (part[2] != null) {
      const index = Number(part[2]);
      if (!Number.isInteger(index) || index < 0 || index > MAX_INDEX) return null;
      segments.push({ kind: "index", index });
    } else {
      segments.push({ kind: "all" });
    }
  }
  return segments;
}

export function getAtPath(value: unknown, segments: readonly PathSegment[]): unknown {
  let current = value;
  for (const segment of segments) {
    if (current == null) return undefined;
    if (segment.kind === "key") {
      if (typeof current !== "object" || Array.isArray(current)) return undefined;
      if (!Object.hasOwn(current, segment.name)) return undefined;
      current = (current as Record<string, unknown>)[segment.name];
      continue;
    }
    if (segment.kind === "all") return undefined;
    if (!Array.isArray(current) || !Number.isInteger(segment.index) || segment.index < 0) {
      return undefined;
    }
    if (!Object.hasOwn(current, segment.index)) return undefined;
    current = current[segment.index];
  }
  return current;
}

export function formatPath(segments: readonly PathSegment[]): string {
  let out = "";
  for (const segment of segments) {
    if (segment.kind === "key") {
      out = out === "" ? segment.name : `${out}.${segment.name}`;
    } else if (segment.kind === "all") {
      out += "[]";
    } else {
      out += `[${segment.index}]`;
    }
  }
  return out;
}
