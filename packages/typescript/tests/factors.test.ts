import { describe, expect, test } from "bun:test";
import type { Questions } from "../src/index.ts";
import {
  type AnswersFor,
  checkDefinition,
  createFactorEvaluator,
  parseDefinition,
  SystemOnePromptsError,
} from "../src/index.ts";
import { fixture } from "./helpers.ts";

const questionsToml = `
[questions.topic]
type = "choice"
instructions = "Which?"
[questions.topic.criteria]
billing = "Charges"
orders = "Shipments"

[questions.refund_requested]
type = "noul"
instructions = "Refund?"

[questions.frustration]
type = "score"
instructions = "How frustrated?"
criteria = ["Calm", "Civil", "Angry"]

[questions.a]
type = "noul"
instructions = "a"

[questions.b]
type = "noul"
instructions = "b"

[questions.c]
type = "noul"
instructions = "c"
`;

function factorsOf(body: string) {
  const def = parseDefinition(`${questionsToml}\n[factors]\n${body}\n`);
  const diags = checkDefinition(def);
  expect(diags.filter((d) => d.severity === "error")).toEqual([]);
  return createFactorEvaluator(def.factorDefinitions);
}

const answers: AnswersFor<Questions> = {
  topic: {
    type: "choice",
    choice: "billing",
    confidence: 0.8,
    probabilities: { billing: 0.8, orders: 0.2 },
  },
  refund_requested: { type: "noul", noul: 0.7 },
  frustration: {
    type: "score",
    score: 1.6,
    confidence: 0.72,
    legend: { "0": "Calm", "1": "Civil", "2": "Angry" },
    probabilities: { "0": 0.1, "1": 0.2, "2": 0.7 },
  },
  a: { type: "noul", noul: 0.9 },
  b: { type: "noul", noul: 0.2 },
  c: { type: "noul", noul: 0.6 },
};

describe("evaluateFactors", () => {
  test("predicates match TypeSafe fields", () => {
    const evaluate = factorsOf(`
"topic.billing" = { ref = "topic", choice = "billing" }
"topic.billing.confident" = { ref = "topic", choice = "billing", confidence = { gte = 0.75 } }
"refund.strong" = { ref = "refund_requested", noul = { gte = 0.7 } }
"spam.gray" = { ref = "refund_requested", noul = { gt = 0.4, lt = 0.6 } }
"high.frustrated" = { ref = "frustration", score = { gte = 1.5 }, confidence = { gte = 0.7 } }
`);
    expect(evaluate(answers)).toEqual({
      "topic.billing": true,
      "topic.billing.confident": true,
      "refund.strong": true,
      "spam.gray": false,
      "high.frustrated": true,
    });
  });

  test("bare Noul in Boolean context uses 0.5", () => {
    const evaluate = factorsOf(`
ready = { all = ["a", "c"] }
partial = { any = ["a", "b"] }
blocked = { not = "b" }
`);
    expect(evaluate(answers)).toEqual({
      ready: true,
      partial: true,
      blocked: true,
    });
    const atBoundary = factorsOf(`edge = { all = ["a"] }`);
    expect(atBoundary({ a: { type: "noul", noul: 0.5 } }).edge).toBe(true);
    expect(atBoundary({ a: { type: "noul", noul: 0.499 } }).edge).toBe(false);
  });

  test("nested factor counts as one vote", () => {
    const evaluate = factorsOf(`
pair = { all = ["a", "c"] }
votes = { at_least = 2, of = ["pair", "b"] }
`);
    expect(evaluate(answers).votes).toBe(false);
    const evaluate2 = factorsOf(`
pair = { all = ["a", "c"] }
votes = { at_least = 2, of = ["pair", "c"] }
`);
    expect(evaluate2(answers).votes).toBe(true);
  });

  test("ANDed comparators", () => {
    const evaluate = factorsOf(
      `band = { ref = "refund_requested", noul = { gt = 0.4, lt = 0.8 } }`,
    );
    expect(evaluate(answers).band).toBe(true);
    expect(evaluate({ refund_requested: { type: "noul", noul: 0.4 } }).band).toBe(false);
    expect(evaluate({ refund_requested: { type: "noul", noul: 0.8 } }).band).toBe(false);
  });

  test("missing answers are errors, never false", () => {
    const evaluate = factorsOf(`ready = { all = ["a"] }`);
    expect(() => evaluate({})).toThrow(SystemOnePromptsError);
    expect(() => evaluate({})).toThrow(/missing answer `a`/);
    const notReady = factorsOf(`flipped = { not = "a" }`);
    expect(() => notReady({})).toThrow(/missing answer `a`/);
  });

  test("all and any inspect every reference before returning", () => {
    const all = createFactorEvaluator({ ready: { all: ["a", "missing"] } });
    expect(() => all({ a: { type: "noul", noul: 0.9 } })).toThrow(/missing answer `missing`/);

    const any = createFactorEvaluator({ ready: { any: ["a", "missing"] } });
    expect(() => any({ a: { type: "noul", noul: 0.9 } })).toThrow(/missing answer `missing`/);
  });

  test("compiled evaluators snapshot definitions and use prototype-safe ids", () => {
    const defs = Object.create(null) as Record<string, Record<string, unknown>>;
    Object.defineProperty(defs, "__proto__", {
      value: { all: ["a"] },
      enumerable: true,
    });
    Object.defineProperty(defs, "constructor", {
      value: { all: ["a"] },
      enumerable: true,
    });
    defs.result = { all: ["__proto__", "constructor"] };

    const evaluate = createFactorEvaluator(defs);
    defs.later = { all: ["a"] };
    const result = evaluate({ a: { type: "noul", noul: 0.9 } });

    expect(Object.getPrototypeOf(result)).toBeNull();
    expect(Object.keys(result)).toEqual(["__proto__", "constructor", "result"]);
    expect(Object.hasOwn(result, "__proto__")).toBe(true);
    expect(Reflect.get(result, "__proto__")).toBe(true);
    expect(Reflect.get(result, "constructor")).toBe(true);
    expect(Object.hasOwn(result, "later")).toBe(false);
  });

  test("answer references require own properties", () => {
    const evaluate = createFactorEvaluator({ ready: { all: ["a"] } });
    const inheritedAnswers = Object.create({ a: { type: "noul", noul: 0.9 } });
    expect(() => evaluate(inheritedAnswers)).toThrow(/missing answer `a`/);
  });

  test("known predicates use missing / p=0.5 / confidence-0 as unknown", () => {
    const evaluate = factorsOf(`
present = { ref = "refund_requested", known = true }
absent = { ref = "refund_requested", known = false }
strong_known = { ref = "refund_requested", known = true, noul = { gte = 0.5 } }
`);
    expect(evaluate({ refund_requested: { type: "noul", noul: 0.7 } })).toEqual({
      present: true,
      absent: false,
      strong_known: true,
    });
    expect(evaluate({ refund_requested: { type: "noul", noul: 0.5 } })).toEqual({
      present: false,
      absent: true,
      strong_known: false,
    });
    expect(evaluate({ refund_requested: { type: "noul", noul: 0.49 } })).toEqual({
      present: true,
      absent: false,
      strong_known: false,
    });
    expect(
      evaluate({
        refund_requested: { type: "noul", noul: 0.5, missing: true },
      } as AnswersFor<Questions>),
    ).toEqual({
      present: false,
      absent: true,
      strong_known: false,
    });
    expect(evaluate({})).toEqual({
      present: false,
      absent: true,
      strong_known: false,
    });
  });

  test("known on Choice follows confidence, not the label alone", () => {
    const evaluate = factorsOf(`
pref_faster = { ref = "topic", known = true, choice = "billing" }
`);
    expect(
      evaluate({
        topic: {
          type: "choice",
          choice: "billing",
          confidence: 0,
          probabilities: { billing: 1, orders: 0 },
        },
      }).pref_faster,
    ).toBe(false);
    expect(
      evaluate({
        topic: {
          type: "choice",
          choice: "billing",
          confidence: 0.8,
          probabilities: { billing: 0.8, orders: 0.2 },
        },
      }).pref_faster,
    ).toBe(true);
  });

  test("known = false with a value comparator still errors on a missing body", () => {
    const evaluate = factorsOf(`x = { ref = "a", known = false, noul = { gte = 0.5 } }`);
    expect(() => evaluate({})).toThrow(/missing answer `a`/);
  });

  test("rejects nonfinite comparator and answer numbers", () => {
    expect(() =>
      createFactorEvaluator({ threshold: { ref: "a", noul: { gte: Number.POSITIVE_INFINITY } } }),
    ).toThrow(/must be a finite number/);
    expect(() =>
      createFactorEvaluator({ threshold: { ref: "a", noul: { gte: 0.5 } } })({
        a: { type: "noul", noul: Number.NaN },
      }),
    ).toThrow(/must be finite/);
  });
});

describe("factor compile errors", () => {
  const cases = [
    {
      file: "unknown-option.toml",
      code: "unknown-option",
      message: /unknown option `billling`/,
      hint: /billing, orders, account/,
    },
    {
      file: "score-as-boolean.toml",
      code: "non-boolean-ref",
      message: /Score `frustration` used directly in `all`/,
    },
    {
      file: "noul-confidence.toml",
      code: "noul-confidence",
      message: /confidence` is not available on Noul `refund_requested`/,
    },
    {
      file: "cycle.toml",
      code: "cycle",
      message: /cycle: a → b → a/,
    },
    {
      file: "collision.toml",
      code: "id-collision",
      message: /factor `topic` collides with question `topic`/,
    },
  ] as const;

  for (const item of cases) {
    test(item.file, () => {
      const def = parseDefinition(fixture(`errors/${item.file}`), { filename: item.file });
      const error = checkDefinition(def).find((d) => d.severity === "error");
      expect(error?.code).toBe(item.code);
      expect(error?.message).toMatch(item.message);
      if ("hint" in item) expect(error?.hint).toMatch(item.hint);
      // The location is the offending factor's own line, not the [factors] header.
      const source = fixture(`errors/${item.file}`).split("\n");
      expect(error?.line).toBeGreaterThan(source.indexOf("[factors]") + 1);
      expect(source[(error?.line ?? 0) - 1]).toContain("=");
    });
  }

  const inline: Array<{ name: string; body: string; code: string; message: RegExp }> = [
    {
      name: "unknown ref in operator",
      body: `x = { all = ["a", "nope"] }`,
      code: "unknown-ref",
      message: /unknown id `nope`/,
    },
    {
      name: "predicate on unknown question",
      body: `x = { ref = "nope", noul = { gte = 0.5 } }`,
      code: "unknown-ref",
      message: /unknown question `nope`/,
    },
    {
      name: "choice on a Noul",
      body: `x = { ref = "a", choice = "yes" }`,
      code: "choice-on-non-choice",
      message: /`choice` is not available on Noul `a`/,
    },
    {
      name: "noul comparator on a Choice",
      body: `x = { ref = "topic", noul = { gte = 0.5 } }`,
      code: "noul-on-non-noul",
      message: /`noul` is not available on Choice `topic`/,
    },
    {
      name: "score comparator on a Noul",
      body: `x = { ref = "a", score = { gte = 1 } }`,
      code: "score-on-non-score",
      message: /`score` is not available on Noul `a`/,
    },
    {
      name: "ref mixed with operator",
      body: `x = { ref = "a", noul = { gte = 0.5 }, all = ["b"] }`,
      code: "factor-mixed",
      message: /cannot mix/,
    },
    {
      name: "two operators",
      body: `x = { all = ["a"], any = ["b"] }`,
      code: "factor-mixed",
      message: /several operators \(all, any\)/,
    },
    {
      name: "predicate without a field",
      body: `x = { ref = "a" }`,
      code: "predicate-empty",
      message: /needs one of known \/ choice \/ noul \/ score \/ confidence/,
    },
    {
      name: "known must be boolean",
      body: `x = { ref = "a", known = "yes" }`,
      code: "predicate-known",
      message: /`known` must be a boolean/,
    },
    {
      name: "unknown comparator key",
      body: `x = { ref = "a", noul = { eq = 0.5 } }`,
      code: "comparator-keys",
      message: /unknown comparator `eq`/,
    },
    {
      name: "at_least without count",
      body: `x = { of = ["a", "b"] }`,
      code: "at-least-count",
      message: /positive integer/,
    },
    {
      name: "unknown factor field",
      body: `x = { ref = "a", noul = { gte = 0.5 }, weight = 2 }`,
      code: "unknown-factor-field",
      message: /unknown field `weight`/,
    },
    {
      name: "of is only allowed with at_least",
      body: `x = { all = ["a"], of = ["a"] }`,
      code: "unknown-factor-field",
      message: /unknown field `of`/,
    },
    {
      name: "of is not allowed with any",
      body: `x = { any = ["a"], of = ["a"] }`,
      code: "unknown-factor-field",
      message: /unknown field `of`/,
    },
    {
      name: "of is not allowed with not",
      body: `x = { not = "a", of = ["a"] }`,
      code: "unknown-factor-field",
      message: /unknown field `of`/,
    },
    {
      name: "predicate fields require ref",
      body: `x = { choice = "billing" }`,
      code: "unknown-factor-field",
      message: /unknown field `choice`/,
    },
  ];

  for (const item of inline) {
    test(item.name, () => {
      const def = parseDefinition(`${questionsToml}\n[factors]\n${item.body}\n`);
      const error = checkDefinition(def).find((d) => d.severity === "error");
      expect(error?.code).toBe(item.code);
      expect(error?.message).toMatch(item.message);
    });
  }

  test("createFactorEvaluator rejects broken tables up front", () => {
    expect(() => createFactorEvaluator({ x: { all: ["a"], any: ["b"] } })).toThrow(
      SystemOnePromptsError,
    );
    expect(() => createFactorEvaluator({ a: { not: "b" }, b: { not: "a" } })).toThrow(/cycle/);
    expect(() => createFactorEvaluator(undefined as never)).toThrow(/factorDefinitions/);
  });

  test("reports independent cycles together", () => {
    let thrown: unknown;
    try {
      createFactorEvaluator({
        a: { not: "b" },
        b: { not: "a" },
        c: { not: "d" },
        d: { not: "c" },
      });
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toBeInstanceOf(SystemOnePromptsError);
    const diagnostics = (thrown as SystemOnePromptsError).diagnostics;
    expect(diagnostics.filter((d) => d.code === "cycle").map((d) => d.message)).toEqual([
      "cycle: a → b → a",
      "cycle: c → d → c",
    ]);
  });
});
