import { expect, test } from "bun:test";

test("core modules do not import the CLI", async () => {
  const files: string[] = [];
  for await (const file of new Bun.Glob(
    "src/{definition,questions,state,factors,generate,patterns}/**/*.ts",
  ).scan()) {
    files.push(file);
  }
  const violations: string[] = [];
  for (const file of files) {
    const content = await Bun.file(file).text();
    if (content.includes("/cli/") || content.includes("../cli")) violations.push(file);
  }
  expect(violations).toEqual([]);
});
