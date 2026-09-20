import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  checkDefinition,
  createFactorEvaluator,
  createStateAssert,
  errorsOf,
  parseDefinition,
  type StateAssert,
} from "systemoneprompts";

const CORPUS = join(import.meta.dir, "../../conformance/v1");
const manifest = JSON.parse(readFileSync(join(CORPUS, "manifest.json"), "utf8")) as {
  cases: string[];
  operations?: Record<string, string[]>;
};

for (const caseId of manifest.cases) {
  test(`v1 conformance case ${caseId}`, () => {
    const root = join(CORPUS, "cases", caseId);
    const definition = parseDefinition(readFileSync(join(root, "definition.toml"), "utf8"));
    const errors = errorsOf(checkDefinition(definition));
    if (errors.length > 0) throw new Error(errors.map((item) => item.message).join("\n"));

    const operations = manifest.operations?.[caseId] ?? ["parse"];
    const expected = JSON.parse(readFileSync(join(root, "expected.json"), "utf8")) as Record<
      string,
      unknown
    >;
    const actual: Record<string, unknown> = {};
    if (operations.includes("assert_state")) {
      try {
        const assertState: StateAssert = createStateAssert(definition.requires);
        assertState(JSON.parse(readFileSync(join(root, "state.json"), "utf8")));
        actual.state_valid = true;
      } catch {
        actual.state_valid = false;
      }
    }
    if (operations.includes("evaluate_factors")) {
      actual.factors = createFactorEvaluator(definition.factorDefinitions)(
        JSON.parse(readFileSync(join(root, "answers.json"), "utf8")),
      );
    }
    expect(actual).toEqual(expected);

    if (caseId === "basic") {
      expect(definition.questions.topic).toEqual({
        type: "choice",
        criteria: { billing: "Billing", orders: "Orders" },
      });
      expect(definition.data).toEqual({
        labels: { billing: "Billing", orders: "Orders" },
        variants: ["first", "second"],
        nested: { message: "Application-owned text stays outside the provider questions.\n" },
      });
    }
  });
}
