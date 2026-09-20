import { describe, expect, test } from "bun:test";
import { checkDefinition, generate, parseDefinition } from "../src/index.ts";
import { fixture } from "./helpers.ts";

describe("native question objects", () => {
  test("rejects missing or empty questions before generation", () => {
    for (const source of ['title = "empty"', "[questions]"]) {
      expect(checkDefinition(parseDefinition(source)).map((d) => d.code)).toContain(
        "questions-empty",
      );
      expect(() => generate(source)).toThrow("at least one question");
    }
  });

  test("rejects TOML dates wherever JSON descriptions are expected", () => {
    for (const field of [
      "instructions = 2024-01-01T00:00:00Z",
      "instructions = { when = 2024-01-01 }",
      "instructions = [2024-01-01]",
      "criteria = { true = 2024-01-01 }",
    ]) {
      const source = `[questions.q]\ntype = "noul"\n${field}`;
      expect(checkDefinition(parseDefinition(source)).some((d) => d.severity === "error")).toBe(
        true,
      );
      expect(() => generate(source)).toThrow();
    }
  });

  test("preserves prototype-named question IDs and metadata as own keys", () => {
    const def = parseDefinition(`
"__proto__" = "metadata"
[questions."__proto__"]
type = "noul"
[questions.constructor]
type = "noul"
[questions.toString]
type = "noul"
`);
    expect(checkDefinition(def)).toEqual([]);
    expect(Object.keys(def.questions)).toEqual(["__proto__", "constructor", "toString"]);
    expect(Object.hasOwn(def.meta, "__proto__")).toBe(true);
    expect(Object.getOwnPropertyDescriptor(def.meta, "__proto__")?.value).toBe("metadata");
  });

  test("triage questions deep-equal hand-written native question objects", () => {
    const def = parseDefinition(fixture("golden/triage.toml"));
    expect(def.questions.topic).toEqual({
      type: "choice",
      instructions: {
        question: "Which team should handle `ticket.message`?",
        focus: "Classify the customer's primary request.",
      },
      criteria: {
        billing: {
          what: "Charges, invoices, refunds, or subscriptions",
          not_for: "Order tracking or account access",
          examples: ["I was charged twice", "Where is my refund?"],
        },
        orders: {
          what: "Order status, delivery, cancellation, or returns",
          not_for: "Charges or account access",
          examples: ["Where is my order?", "Cancel my shipment"],
        },
        account: {
          what: "Login, profile, permissions, or security",
          not_for: "Charges or order tracking",
          examples: ["Reset my password", "I cannot sign in"],
        },
      },
    });
    expect(def.questions["spam.requests_credentials"]).toEqual({
      type: "noul",
      instructions: {
        question: "Does the message request a sensitive credential?",
        compare: ["`ticket.message`", "`policy.sensitive_credentials`"],
        focus: "Look for a request to disclose the credential itself.",
      },
      criteria: {
        true: {
          what: "Asks the recipient to disclose a listed credential",
          examples: ["Reply with your password", "Send us your API key"],
        },
        false: {
          what: "Does not ask the recipient to disclose a credential",
          not_for: "A legitimate instruction to reset a credential",
          examples: ["Use this link to reset your password"],
        },
      },
    });
    expect(def.questions.frustration).toEqual({
      type: "score",
      instructions: {
        question: "How frustrated does the customer appear?",
        inspect: "`ticket.message`",
      },
      criteria: [
        { what: "Calm and matter-of-fact", signals: ["Neutral wording"] },
        { what: "Frustrated but civil" },
        { what: "Very angry or threatening to leave" },
      ],
    });
  });

  test("docs API examples round-trip", () => {
    expect(parseDefinition(fixture("golden/noul-string.toml")).questions).toEqual({
      is_urgent: {
        type: "noul",
        instructions: "Does this convey urgency?",
        criteria: { true: "Explicitly time-sensitive", false: "No urgency expressed" },
      },
    });
    expect(parseDefinition(fixture("golden/choice-strings.toml")).questions).toEqual({
      department: {
        type: "choice",
        instructions: "Which team should handle this?",
        criteria: {
          billing: "Payments, invoicing, refunds",
          technical: "Bugs, outages, integrations",
          sales: "Pricing, upgrades, new accounts",
        },
      },
    });
    expect(parseDefinition(fixture("golden/score-strings.toml")).questions).toEqual({
      frustration: {
        type: "score",
        instructions: "How frustrated is the customer?",
        criteria: ["Calm", "Frustrated", "Very angry"],
      },
    });
  });

  test("structured field instructions are forwarded verbatim", () => {
    const def = parseDefinition(fixture("golden/field-instructions.toml"));
    expect(def.questions.amount_present).toEqual({
      type: "noul",
      instructions: {
        field: { name: "total", type: "currency" },
        question: "Is a total amount present on the invoice?",
      },
      criteria: {
        true: "A numeric total is stated",
        false: "No total is recoverable",
      },
    });
  });
});
