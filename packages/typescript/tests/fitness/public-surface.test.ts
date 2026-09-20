import { expect, test } from "bun:test";

test("library entry point does not export CLI or test internals", async () => {
  const content = await Bun.file("src/index.ts").text();
  expect(content).not.toContain("./cli/");
  expect(content).not.toContain("../tests/");
});
