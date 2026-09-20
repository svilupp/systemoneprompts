import { type PathSegment, parsePath } from "../state/paths.js";
import type { Requirements, RequirementType } from "../state/requirements.js";

type TypeNode =
  | { kind: "leaf"; ts: string }
  | { kind: "object"; props: Map<string, TypeNode> }
  | { kind: "array"; element: TypeNode };

const jsonValue = (): TypeNode => ({ kind: "leaf", ts: "JsonValue" });

/**
 * Emit `export interface RequiredState { … }` from `[requires]`. Every object level
 * carries a `JsonValue` index signature, so the narrowed state is still a valid
 * `EntryType` and can be passed straight to `TypeSafeClient.systemOne`. Index paths
 * (`tickets[0].message` / `tickets[].message`) become element types; `[]` asserts
 * every element at runtime.
 */
export function emitRequiredState(requires: Requirements): string {
  if (Object.keys(requires).length === 0) {
    return "export type RequiredState = EntryType;";
  }

  const root = { kind: "object" as const, props: new Map<string, TypeNode>() };
  for (const [path, type] of Object.entries(requires)) {
    const segments = parsePath(path);
    if (!segments) continue;
    addPath(root, segments, leafFor(type));
  }
  return `export interface RequiredState ${printObject(root.props, 0)}`;
}

function leafFor(type: RequirementType): TypeNode {
  switch (type) {
    case "string":
      return { kind: "leaf", ts: "string" };
    case "number":
      return { kind: "leaf", ts: "number" };
    case "boolean":
      return { kind: "leaf", ts: "boolean" };
    case "null":
      return { kind: "leaf", ts: "null" };
    case "exists":
      return jsonValue();
    case "array":
      return { kind: "array", element: jsonValue() };
    case "object":
      return { kind: "object", props: new Map() };
  }
}

function addPath(node: TypeNode, segments: readonly PathSegment[], leaf: TypeNode): void {
  const head = segments[0];
  if (!head) return;

  if (head.kind === "key") {
    if (node.kind !== "object") return;
    if (segments.length === 1) {
      node.props.set(head.name, merge(node.props.get(head.name), leaf));
      return;
    }

    const next = segments[1]!;
    const child = ensureContainer(node.props.get(head.name), next);
    node.props.set(head.name, child);
    addPath(child, segments.slice(1), leaf);
    return;
  }

  if (node.kind !== "array") return;
  if (segments.length === 1) {
    node.element = merge(node.element, leaf);
    return;
  }

  const next = segments[1]!;
  const child = ensureContainer(node.element, next);
  node.element = child;
  addPath(child, segments.slice(1), leaf);
}

function ensureContainer(existing: TypeNode | undefined, next: PathSegment): TypeNode {
  if (next.kind === "index" || next.kind === "all") {
    return existing?.kind === "array"
      ? existing
      : { kind: "array", element: existing ?? jsonValue() };
  }
  return existing?.kind === "object" ? existing : { kind: "object", props: new Map() };
}

function merge(existing: TypeNode | undefined, incoming: TypeNode): TypeNode {
  if (!existing) return incoming;
  if (existing.kind === "leaf" && existing.ts === "JsonValue") return incoming;
  if (incoming.kind === "leaf" && incoming.ts === "JsonValue") return existing;

  if (existing.kind === "object" && incoming.kind === "object") {
    const props = new Map(existing.props);
    for (const [key, node] of incoming.props) {
      props.set(key, merge(props.get(key), node));
    }
    return { kind: "object", props };
  }
  if (existing.kind === "array" && incoming.kind === "array") {
    return { kind: "array", element: merge(existing.element, incoming.element) };
  }
  if (existing.kind === "array" && incoming.kind === "object") {
    return { kind: "array", element: merge(existing.element, incoming) };
  }
  if (existing.kind === "object" && incoming.kind === "array") {
    return { kind: "array", element: merge(existing, incoming.element) };
  }
  return incoming;
}

function printNode(node: TypeNode, indent: number): string {
  switch (node.kind) {
    case "leaf":
      return node.ts;
    case "array":
      return `${printNode(node.element, indent)}[]`;
    case "object":
      return printObject(node.props, indent);
  }
}

function printObject(props: Map<string, TypeNode>, indent: number): string {
  const pad = "  ".repeat(indent + 1);
  const close = "  ".repeat(indent);
  const lines = [...props.entries()].map(([key, node]) => {
    return `${pad}${quoteIdent(key)}: ${printNode(node, indent + 1)};`;
  });
  lines.push(`${pad}[k: string]: JsonValue;`);
  return `{
${lines.join("\n")}
${close}}`;
}

function quoteIdent(name: string): string {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name) ? name : JSON.stringify(name);
}
