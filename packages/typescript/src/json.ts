export function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function isJsonValue(value: unknown): boolean {
  return checkJsonValue(value, new WeakSet<object>());
}

function checkJsonValue(value: unknown, ancestors: WeakSet<object>): boolean {
  if (value === null) return true;
  const t = typeof value;
  if (t === "string" || t === "boolean") return true;
  if (t === "number") return Number.isFinite(value);
  if (!Array.isArray(value) && !isPlainObject(value)) return false;
  if (ancestors.has(value)) return false;
  ancestors.add(value);
  // Iteration visits sparse array slots as undefined; shared references are valid
  // as long as they are not ancestors of the current value.
  for (const child of Array.isArray(value) ? value : Object.values(value)) {
    if (!checkJsonValue(child, ancestors)) return false;
  }
  ancestors.delete(value);
  return true;
}

/** JSON with object keys sorted recursively, so equal values hash identically. */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(sortKeys(value));
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (!isPlainObject(value)) return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, sortKeys(value[key])]),
  );
}

export function typeName(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}
