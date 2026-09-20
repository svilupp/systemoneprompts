import { expect, test } from "bun:test";
import { parseDefinition } from "../src/index.ts";

test("bun can import the library", () => {
  const def = parseDefinition(`
[questions.ok]
type = "noul"
instructions = "ok?"
`);
  expect(def.questions.ok?.type).toBe("noul");
});
