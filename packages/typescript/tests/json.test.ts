import { expect, test } from "bun:test";
import { canonicalJson, isJsonValue, isPlainObject } from "../src/json.ts";

test("plain JSON objects exclude Dates and class instances", () => {
  for (const value of [new Date(), new Map(), new Set(), new (class Example {})()]) {
    expect(isPlainObject(value)).toBe(false);
    expect(isJsonValue({ value })).toBe(false);
  }
  expect(isJsonValue(Object.assign(Object.create(null), { valid: [true, null, 1] }))).toBe(true);
});

test("canonical JSON preserves special keys and distinguishes their values", () => {
  const a = JSON.parse('{"z":0,"__proto__":{"value":1}}');
  const b = JSON.parse('{"__proto__":{"value":2},"z":0}');
  expect(JSON.parse(canonicalJson(a))).toEqual(a);
  expect(canonicalJson(a)).not.toBe(canonicalJson(b));
});

test("JSON validation rejects cycles and sparse arrays but allows shared values", () => {
  const object: Record<string, unknown> = {};
  object.self = object;
  const array: unknown[] = [];
  array.push(array);
  expect(isJsonValue(object)).toBe(false);
  expect(isJsonValue(array)).toBe(false);
  expect(isJsonValue(new Array(1))).toBe(false);

  const shared = { nested: [null, true, 1] };
  expect(isJsonValue({ first: shared, second: shared })).toBe(true);
  expect(isJsonValue([shared, shared])).toBe(true);
});
