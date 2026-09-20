import { describe, expect, test } from "bun:test";
import {
  checkDefinition,
  createStateAssert,
  parseDefinition,
  type StateAssert,
  SystemOnePromptsError,
} from "../src/index.ts";
import { parsePath } from "../src/state/paths.ts";
import { fixture } from "./helpers.ts";

const requires = {
  "ticket.message": "string",
  "customer.open_orders": "array",
  policy: "object",
  "metadata.legacy": "exists",
  "support.tickets[0].message": "string",
} as const;

const assertState: StateAssert = createStateAssert(requires);

const valid = {
  ticket: { message: "hello", extra: true },
  customer: { open_orders: [{ id: "A-1" }], plan: "pro" },
  policy: { sensitive_credentials: ["password"] },
  metadata: { legacy: null, other: 1 },
  support: { tickets: [{ message: "first", id: 1 }] },
  leftover: "ok",
};

describe("createStateAssert", () => {
  test("empty requirements accept every EntryType value at runtime", () => {
    const emptyAssert: StateAssert = createStateAssert({});
    for (const state of ["text", null, [], { nested: true }]) {
      emptyAssert(state);
    }
  });

  test("required present passes and does not copy", () => {
    const before = structuredClone(valid);
    assertState(valid);
    expect(Object.is(valid, valid)).toBe(true);
    expect(valid).toEqual(before);
  });

  test("missing path names the path", () => {
    expect(() => assertState({ ...valid, ticket: {} })).toThrow(SystemOnePromptsError);
    try {
      assertState({ ...valid, ticket: {} });
    } catch (error) {
      expect(error).toBeInstanceOf(SystemOnePromptsError);
      expect((error as SystemOnePromptsError).message).toContain(
        "ticket.message: expected string, got undefined",
      );
    }
  });

  test("wrong type names the path", () => {
    try {
      assertState({ ...valid, customer: { open_orders: "none" } });
    } catch (error) {
      expect((error as SystemOnePromptsError).message).toContain(
        "customer.open_orders: expected array, got string",
      );
    }
  });

  test("exists accepts null", () => {
    assertState(valid);
  });

  test("object and array requirements reject non-JSON values", () => {
    const objectAssert: StateAssert = createStateAssert({ value: "object" });
    const arrayAssert: StateAssert = createStateAssert({ value: "array" });
    const invalid = [
      new Date(),
      new Map(),
      new Set(),
      new (class Example {})(),
      undefined,
      () => {},
      Symbol("value"),
      1n,
      Number.NaN,
      Number.POSITIVE_INFINITY,
    ];
    for (const value of invalid) {
      expect(() => objectAssert({ value })).toThrow(SystemOnePromptsError);
      expect(() => objectAssert({ value: { nested: value } })).toThrow(SystemOnePromptsError);
      expect(() => arrayAssert({ value: [value] })).toThrow(SystemOnePromptsError);
    }
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;
    expect(() => objectAssert({ value: cyclic })).toThrow(SystemOnePromptsError);
    expect(() => arrayAssert({ value: [cyclic] })).toThrow(SystemOnePromptsError);
    expect(() => arrayAssert({ value: new Array(1) })).toThrow(SystemOnePromptsError);
  });

  test("JSON containers preserve null prototypes, special keys, and shared references", () => {
    const containerAssert: StateAssert = createStateAssert({ object: "object", array: "array" });
    const shared = Object.assign(Object.create(null), { valid: [true, null, 1, "text"] });
    const state = {
      object: { ...JSON.parse('{"__proto__":"ordinary key"}'), first: shared, second: shared },
      array: [shared, shared],
    };
    containerAssert(state);
    expect(state.object.first).toBe(shared);
    expect(state.array[0]).toBe(shared);
  });

  test("extra root and nested fields pass", () => {
    assertState({ ...valid, another: { nested: true } });
  });

  test("invalid paths fail at construction, not first use", () => {
    expect(() => createStateAssert({ "bad path": "string" } as never)).toThrow(
      SystemOnePromptsError,
    );
  });

  test("requires own properties and supports the __proto__ path", () => {
    const ticketAssert: StateAssert = createStateAssert({ "ticket.message": "string" });
    const inherited = Object.create({ ticket: { message: "inherited" } });
    expect(() => ticketAssert(inherited)).toThrow("ticket.message: expected string, got undefined");

    const own = Object.create({ ticket: { message: "inherited" } }) as Record<string, unknown>;
    own.ticket = { message: "own" };
    ticketAssert(own);

    const protoState = JSON.parse('{"__proto__":{"value":"ok"}}') as unknown;
    const protoAssert: StateAssert = createStateAssert({ "__proto__.value": "string" });
    protoAssert(protoState);
  });

  test("canonicalizes index aliases and rejects indexes outside array bounds", () => {
    expect(parsePath("items[01].value")).toEqual([
      { kind: "key", name: "items" },
      { kind: "index", index: 1 },
      { kind: "key", name: "value" },
    ]);
    expect(parsePath("items[4294967294]")).not.toBeNull();
    expect(parsePath("items[4294967295]")).toBeNull();
    expect(parsePath("items[9007199254740992]")).toBeNull();
  });

  test("parses [] as every array element", () => {
    expect(parsePath("[]")).toBeNull();
    expect(parsePath("messages[].text")).toEqual([
      { kind: "key", name: "messages" },
      { kind: "all" },
      { kind: "key", name: "text" },
    ]);
  });

  test("[] requires every element and treats an empty array as success", () => {
    const assertAll: StateAssert = createStateAssert({ "messages[].text": "string" });
    assertAll({ messages: [] });
    assertAll({ messages: [{ text: "a" }, { text: "b" }] });
    try {
      assertAll({ messages: [{ text: "a" }, { text: 1 }] });
      throw new Error("expected failure");
    } catch (error) {
      expect((error as SystemOnePromptsError).message).toContain(
        "messages[].text: expected string, got number",
      );
    }
    expect(() => assertAll({ messages: "bad" })).toThrow("messages: expected array, got string");
    expect(() => assertAll({})).toThrow("messages: expected array, got undefined");
    const nested: StateAssert = createStateAssert({ "grid[][]": "number" });
    nested({ grid: [[1, 2], []] });
    expect(() => nested({ grid: [[1], 2] })).toThrow("grid[]: expected array, got number");
    try {
      assertAll({ messages: { text: "a" } });
      throw new Error("expected failure");
    } catch (error) {
      expect((error as SystemOnePromptsError).message).toContain(
        "messages: expected array, got object",
      );
    }
  });
});

describe("[requires] checks", () => {
  test("a scalar path that is a prefix of another path is a conflict", () => {
    const def = parseDefinition(`
[requires]
"ticket" = "string"
"ticket.message" = "string"
"items" = "number"
"items[0]" = "string"
"ok" = "object"
"ok.child" = "string"

[questions.q]
type = "noul"
`);
    const errors = checkDefinition(def).filter((d) => d.code === "require-conflict");
    expect(errors.map((d) => d.message)).toEqual([
      "[requires] `ticket` is `string` but `ticket.message` requires it to be a container",
      "[requires] `items` is `number` but `items[0]` requires it to be a container",
    ]);
    expect(errors[1]?.hint).toContain('"array"');
  });

  test("invalid paths and types are reported with locations", () => {
    const def = parseDefinition(
      `[requires]\n"a b" = "string"\n"ok" = "text"\n\n[questions.q]\ntype = "noul"\n`,
      {
        filename: "r.toml",
      },
    );
    const codes = def.diagnostics.map((d) => [d.code, d.line]);
    expect(codes).toEqual([
      ["invalid-require-path", 2],
      ["invalid-require-type", 3],
    ]);
  });

  test("rejects incompatible explicit and implicit containers", () => {
    const def = parseDefinition(`
[requires]
as_object = "object"
"as_object[0]" = "string"
as_array = "array"
"as_array.child" = "string"
"mixed.child" = "string"
"mixed[0]" = "string"

[questions.q]
type = "noul"
`);
    const errors = checkDefinition(def).filter((d) => d.code === "require-conflict");
    expect(errors.map((d) => d.message)).toEqual([
      "[requires] `as_object` is `object` but `as_object[0]` requires it to be an array",
      "[requires] `as_array` is `array` but `as_array.child` requires it to be an object",
      "[requires] `mixed.child` and `mixed[0]` require `mixed` to be both an array and an object",
    ]);
  });

  test("[] and [n] do not conflict; object vs [] still does", () => {
    const mixedIndexes = parseDefinition(`
[requires]
"messages[].text" = "string"
"messages[0].id" = "string"

[questions.q]
type = "noul"
`);
    expect(checkDefinition(mixedIndexes).filter((d) => d.code === "require-conflict")).toEqual([]);

    const objectVsAll = parseDefinition(`
[requires]
as_object = "object"
"as_object[]" = "string"
"mixed.child" = "string"
"mixed[]" = "string"

[questions.q]
type = "noul"
`);
    expect(
      checkDefinition(objectVsAll)
        .filter((d) => d.code === "require-conflict")
        .map((d) => d.message),
    ).toEqual([
      "[requires] `as_object` is `object` but `as_object[]` requires it to be an array",
      "[requires] `mixed.child` and `mixed[]` require `mixed` to be both an array and an object",
    ]);

    const descendant = parseDefinition(`
[requires]
"messages[].x" = "string"
"messages[0].x.y" = "number"

[questions.q]
type = "noul"
`);
    expect(
      checkDefinition(descendant)
        .filter((d) => d.code === "require-conflict")
        .map((d) => d.message),
    ).toEqual([
      "[requires] `messages[].x` is `string` but `messages[0].x.y` requires it to be a container",
    ]);
  });

  test("keeps canonical index aliases distinct for conflict diagnostics", () => {
    const def = parseDefinition(`
[requires]
"items[0]" = "string"
"items[00]" = "number"

[questions.q]
type = "noul"
`);
    expect(Object.keys(def.requires)).toEqual(["items[0]", "items[00]"]);
    const conflict = checkDefinition(def).find((d) => d.code === "require-conflict");
    expect(conflict?.message).toBe(
      "[requires] `items[0]` is required as both `string` and `number`",
    );
    expect(conflict?.line).toBe(3);
  });
});

describe("backtick lint", () => {
  test("warns on a typo with a nearest-match suggestion", () => {
    const def = parseDefinition(fixture("errors/backtick-typo.toml"), { filename: "typo.toml" });
    const warning = checkDefinition(def).find((d) => d.code === "unguaranteed-backtick");
    expect(warning?.severity).toBe("warning");
    expect(warning?.message).toContain("`ticket.mesage`");
    expect(warning?.hint).toContain("`ticket.message`");
  });

  test("prefixes of guaranteed paths count as guaranteed; prose is ignored", () => {
    const def = parseDefinition(`
[requires]
"ticket.sender.email" = "string"
"items[0].sku" = "string"

[questions.q]
type = "noul"
instructions = "Compare \`ticket\`, \`ticket.sender\`, \`items\` and \`items[0]\` with \`some prose here\` and \`ticket.subject\`."
`);
    const warnings = checkDefinition(def).filter((d) => d.code === "unguaranteed-backtick");
    expect(warnings.map((d) => d.message)).toEqual([
      "`ticket.subject` is not guaranteed by [requires]",
    ]);
  });

  test("canonical index aliases count as the same guaranteed path", () => {
    for (const [required, referenced] of [
      ["items[01].sku", "items[1].sku"],
      ["items[1].sku", "items[01].sku"],
    ]) {
      const def = parseDefinition(`
[requires]
"${required}" = "string"

[questions.q]
type = "noul"
instructions = "Inspect \`${referenced}\`."
`);
      expect(checkDefinition(def).filter((d) => d.code === "unguaranteed-backtick")).toEqual([]);
    }
  });

  test("[] guarantees a backticked [n] path; [n] does not guarantee []", () => {
    const allCoversIndex = parseDefinition(`
[requires]
"messages[].text" = "string"

[questions.q]
type = "noul"
instructions = "Inspect \`messages[0].text\`."
`);
    expect(
      checkDefinition(allCoversIndex).filter((d) => d.code === "unguaranteed-backtick"),
    ).toEqual([]);

    const indexDoesNotCoverAll = parseDefinition(`
[requires]
"messages[0].text" = "string"

[questions.q]
type = "noul"
instructions = "Inspect \`messages[].text\`."
`);
    expect(
      checkDefinition(indexDoesNotCoverAll)
        .filter((d) => d.code === "unguaranteed-backtick")
        .map((d) => d.message),
    ).toEqual(["`messages[].text` is not guaranteed by [requires]"]);
  });

  test("quoted dotted question ids keep backtick warning locations", () => {
    const def = parseDefinition(
      `[questions."spam.requests_credentials"]\ntype = "noul"\ninstructions = "Inspect \`missing.path\`."\n`,
      { filename: "question.toml" },
    );
    const warning = checkDefinition(def).find((entry) => entry.code === "unguaranteed-backtick");
    expect(warning).toMatchObject({ filename: "question.toml", line: 1, column: 1 });
  });
});
