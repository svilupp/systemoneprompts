import { describe, expect, test } from "bun:test";
import { checkDefinition, parseDefinition, SystemOnePromptsError } from "../src/index.ts";
import { fixture } from "./helpers.ts";

describe("parseDefinition", () => {
  test("preserves metadata and extra scalars", () => {
    const def = parseDefinition(fixture("golden/triage.toml"), { filename: "triage.toml" });
    expect(def.meta.title).toBe("Support ticket triage");
    expect(def.meta.version).toBe("0.1.0");
    expect(def.meta.owner).toBe("support-platform");
    expect(def.model).toBe("jev-latest");
  });

  test("preserves arbitrary application data and defaults it to an empty object", () => {
    const def = parseDefinition(`
[data]
labels = { billing = "Billing", orders = "Orders" }
variants = ["first", "second"]
[data.nested]
message = "Application-owned text"
[questions.ok]
type = "noul"
`);
    expect(def.data).toEqual({
      labels: { billing: "Billing", orders: "Orders" },
      variants: ["first", "second"],
      nested: { message: "Application-owned text" },
    });
    expect(parseDefinition('[questions.ok]\ntype = "noul"').data).toEqual({});
  });

  test("rejects invalid application data without treating it as an unknown table", () => {
    const invalidRoot = parseDefinition('data = "not a table"\n[questions.ok]\ntype = "noul"', {
      filename: "invalid-data.toml",
    });
    expect(invalidRoot.data).toEqual({});
    expect(invalidRoot.diagnostics.map((item) => item.code)).toContain("data-type");
    expect(invalidRoot.diagnostics.map((item) => item.code)).not.toContain("unknown-table");

    const invalidChild = parseDefinition(
      '[data]\ncreated = 2026-09-20T12:00:00Z\n[questions.ok]\ntype = "noul"',
      { filename: "invalid-data.toml" },
    );
    expect(invalidChild.data).toEqual({});
    expect(invalidChild.diagnostics.map((item) => item.code)).toContain("data-json");
  });

  test("preserves arbitrary JSON-compatible application data", () => {
    const def = parseDefinition(
      `
[data]
title = "Delivery"
"__proto__" = { value = "safe" }
nested = { labels = ["one", { quoted = true }], text = """line 1
line 2""" }

[[data.records]]
id = "cost"
labels = ["price", "charge"]

[[data.records]]
id = "timing"
labels = ["when"]

[questions.ok]
type = "noul"
`,
      { filename: "data.toml" },
    );

    expect(def.data).toEqual({
      title: "Delivery",
      ["__proto__"]: { value: "safe" },
      nested: { labels: ["one", { quoted: true }], text: "line 1\nline 2" },
      records: [
        { id: "cost", labels: ["price", "charge"] },
        { id: "timing", labels: ["when"] },
      ],
    });
    expect(Object.hasOwn(def.data, "__proto__")).toBe(true);
    expect(def.diagnostics).toEqual([]);
  });

  test("uses an empty data object when data is absent", () => {
    const def = parseDefinition('[questions.ok]\ntype = "noul"');
    expect(def.data).toEqual({});
    expect(Object.keys(def.data)).toEqual([]);
  });

  test("rejects a non-table data root", () => {
    const def = parseDefinition('data = "owned by the app"\n[questions.ok]\ntype = "noul"', {
      filename: "data-root.toml",
    });
    expect(def.data).toEqual({});
    expect(def.diagnostics).toEqual([
      expect.objectContaining({
        code: "data-type",
        severity: "error",
        filename: "data-root.toml",
      }),
    ]);
  });

  test("rejects non-JSON values inside data as one invalid tree", () => {
    const def = parseDefinition(
      `
[data]
when = 1979-05-27T07:32:00Z

[questions.ok]
type = "noul"
`,
      { filename: "data-date.toml" },
    );
    expect(def.data).toEqual({});
    expect(def.diagnostics).toEqual([
      expect.objectContaining({
        code: "data-json",
        severity: "error",
        filename: "data-date.toml",
        line: 3,
      }),
    ]);
  });

  test("quoted question ids stay literal", () => {
    const def = parseDefinition(fixture("golden/triage.toml"));
    expect(def.questions["spam.requests_credentials"]?.type).toBe("noul");
    expect(Object.keys(def.questions)).toContain("spam.requests_credentials");
  });

  test("quoted dotted question ids keep their table location", () => {
    const def = parseDefinition(`[questions."spam.requests_credentials"]\ntype = "maybe"\n`, {
      filename: "quoted.toml",
    });
    const diagnostic = def.diagnostics.find((entry) => entry.code === "invalid-question-type");
    expect(diagnostic).toMatchObject({ filename: "quoted.toml", line: 1, column: 1 });
  });

  test("unknown top-level tables warn", () => {
    const def = parseDefinition(fixture("errors/unknown-table.toml"), { filename: "oops.toml" });
    const diags = checkDefinition(def);
    const warning = diags.find((d) => d.code === "unknown-table");
    expect(warning?.severity).toBe("warning");
    expect(warning?.message).toContain("[question]");
    expect(warning?.hint).toContain("[questions]");
    expect(warning?.filename).toBe("oops.toml");
  });

  test("rejects invalid TOML with a SystemOnePromptsError carrying the line", () => {
    let caught: unknown;
    try {
      parseDefinition("ok = 1\nuh oh = [", { filename: "bad.toml" });
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(SystemOnePromptsError);
    expect((caught as SystemOnePromptsError).diagnostic.code).toBe("toml-syntax");
    expect((caught as SystemOnePromptsError).diagnostic.filename).toBe("bad.toml");
    expect((caught as SystemOnePromptsError).diagnostic.line).toBe(2);
  });

  test("trims a pinned model and flags blanks", () => {
    const pinned = parseDefinition(
      `model = "  jev-2026-06  "\n[questions.ok]\ntype = "noul"\ninstructions = "ok?"`,
    );
    expect(pinned.model).toBe("jev-2026-06");
    const blank = parseDefinition(
      `model = "   "\n[questions.ok]\ntype = "noul"\ninstructions = "ok?"`,
    );
    expect(blank.model).toBeUndefined();
    expect(blank.diagnostics.map((d) => d.code)).toEqual(["model-string"]);
  });

  test("structural problems land in definition.diagnostics and drop the entry", () => {
    const def = parseDefinition(
      `
title = 42
[questions.ok]
type = "noul"
instructions = "ok?"
[questions.broken]
type = "maybe"
[questions.extra]
type = "noul"
instructions = "x"
weight = 1
`,
      { filename: "d.toml" },
    );
    // `broken` is dropped; `extra` is kept with the unknown field stripped, but still an error.
    expect(Object.keys(def.questions)).toEqual(["ok", "extra"]);
    expect(def.questions.extra).toEqual({ type: "noul", instructions: "x" });
    expect(def.diagnostics.map((d) => d.code)).toEqual([
      "meta-string",
      "invalid-question-type",
      "unknown-question-field",
    ]);
    expect(def.diagnostics.every((d) => d.filename === "d.toml" && (d.line ?? 0) > 0)).toBe(true);
    // checkDefinition includes them, so callers never merge the two by hand.
    expect(checkDefinition(def).map((d) => d.code)).toContain("invalid-question-type");
  });

  test("unknown top-level tables suggest the nearest known table", () => {
    const def = parseDefinition(`[factor]\nx = { all = ["a"] }\n[question.a]\ntype = "noul"\n`);
    const hints = def.diagnostics.filter((d) => d.code === "unknown-table").map((d) => d.hint);
    expect(hints).toEqual(["did you mean [factors]?", "did you mean [questions]?"]);
  });
});
