import { describe, expect, test } from "bun:test";
import { indexSource, locate } from "../src/definition/locate.ts";
import { parseDefinition } from "../src/index.ts";

describe("source location indexing", () => {
  test("locates single-quoted keys after decoding them", () => {
    const index = indexSource("[requires]\n'customer.id' = true\n", "definition.toml");

    expect(locate(index, { section: "requires", key: "customer.id" })).toEqual({
      filename: "definition.toml",
      line: 2,
      column: 1,
    });
  });

  test("keeps dotted single-quoted question ids as one path segment", () => {
    const index = indexSource("[questions.'score.dotted']\ntype = \"score\"\n", "definition.toml");

    expect(locate(index, { table: "questions.'score.dotted'" })).toMatchObject({
      line: 1,
      column: 1,
    });
  });

  test("keeps a literal backslash before a single-quoted key's closing quote", () => {
    const index = indexSource("'path\\' = true\n", "definition.toml");

    expect(locate(index, { key: "path\\" })).toMatchObject({ line: 1, column: 1 });
  });

  test("falls back to a nested array-of-table question header", () => {
    const index = indexSource('[[questions.score.criteria]]\nlabel = "Calm"\n', "definition.toml");

    expect(locate(index, { table: "questions.score" })).toEqual({
      filename: "definition.toml",
      line: 1,
      column: 1,
    });
  });

  test("prefers an explicit table header over a nested fallback", () => {
    const index = indexSource(
      '[questions."score.dotted"]\ntype = "score"\n[[questions."score.dotted".criteria]]\nlabel = "Calm"\n',
      "definition.toml",
    );

    expect(locate(index, { table: 'questions."score.dotted"' })).toMatchObject({
      line: 1,
      column: 1,
    });
  });

  test("uses the semantic question path for nested array-of-table diagnostics", () => {
    const definition = parseDefinition(
      "[[questions.'score.dotted'.criteria]]\nlabel = \"Calm\"\n",
      { filename: "definition.toml" },
    );

    expect(
      definition.diagnostics.find((entry) => entry.code === "invalid-question-type"),
    ).toMatchObject({ filename: "definition.toml", line: 1, column: 1 });
  });
});
