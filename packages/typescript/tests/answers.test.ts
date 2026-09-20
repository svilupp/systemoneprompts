import { expect, test } from "bun:test";
import * as answers from "../src/answers.ts";
import {
  choiceLabel,
  isAnswerForQuestion,
  isAnswerShape,
  noulValue,
  partitionAnswers,
  scoreValue,
  wireQuestions,
} from "../src/index.ts";

const noulQuestion = { type: "noul", instructions: "Urgent?" };
const noulAnswer = { type: "noul", noul: 0.8 };
const choiceQuestion = {
  type: "choice",
  instructions: "Which?",
  criteria: { billing: "Billing", orders: "Orders" },
};
const choiceAnswer = {
  type: "choice",
  choice: "billing",
  confidence: 0.9,
  probabilities: { billing: 0.8, orders: 0.2 },
};
const scoreQuestion = {
  type: "score",
  instructions: "How angry?",
  criteria: ["Calm", "Civil", "Angry"],
};
const scoreAnswer = {
  type: "score",
  score: 1.2,
  confidence: 0.7,
  legend: { "0": "Calm", "1": "Civil", "2": "Angry" },
  probabilities: { "0": 0.1, "1": 0.6, "2": 0.3 },
};

test("valid noul, choice, and score answers match their questions", () => {
  expect(isAnswerShape(noulAnswer)).toBe(true);
  expect(isAnswerForQuestion(noulQuestion, noulAnswer)).toBe(true);
  expect(noulValue(noulAnswer)).toBe(0.8);
  expect(choiceLabel(noulAnswer)).toBeUndefined();
  expect(scoreValue(noulAnswer)).toBeUndefined();

  expect(isAnswerShape(choiceAnswer)).toBe(true);
  expect(isAnswerForQuestion(choiceQuestion, choiceAnswer)).toBe(true);
  expect(choiceLabel(choiceAnswer)).toBe("billing");
  expect(noulValue(choiceAnswer)).toBeUndefined();

  expect(isAnswerShape(scoreAnswer)).toBe(true);
  expect(isAnswerForQuestion(scoreQuestion, scoreAnswer)).toBe(true);
  expect(scoreValue(scoreAnswer)).toBe(1.2);
  expect(choiceLabel(scoreAnswer)).toBeUndefined();
});

test("malformed answers fail shape or question checks", () => {
  expect(isAnswerShape({ type: "noul", noul: Number.POSITIVE_INFINITY })).toBe(false);
  expect(isAnswerForQuestion(noulQuestion, { type: "choice", choice: "billing" })).toBe(false);
  expect(
    isAnswerForQuestion(choiceQuestion, {
      type: "choice",
      choice: "billing",
      confidence: 0.9,
      probabilities: { billing: 1 },
    }),
  ).toBe(false);
  expect(
    isAnswerForQuestion(scoreQuestion, {
      type: "score",
      score: 1,
      confidence: 1,
      legend: { "0": "Calm", "1": "Civil" },
      probabilities: { "0": 1, "1": 0, "2": 0 },
    }),
  ).toBe(false);
  expect(noulValue({ type: "noul" })).toBeUndefined();
  expect(choiceLabel({ type: "choice", choice: "billing", confidence: 1 })).toBeUndefined();
  expect(scoreValue({ type: "score", score: 1, confidence: 1, legend: {} })).toBeUndefined();
});

test("wireQuestions keeps type/instructions/criteria and drops extra keys", () => {
  const wired = wireQuestions({
    b: { type: "noul", extra: true, hash: "x" },
    a: { type: "noul", instructions: "A?", extra: 1 },
    c: { type: "choice", instructions: undefined, criteria: { yes: "Yes" }, extra: null },
  });
  expect(Object.keys(wired)).toEqual(["b", "a", "c"]);
  expect(wired).toEqual({
    b: { type: "noul" },
    a: { type: "noul", instructions: "A?" },
    c: { type: "choice", criteria: { yes: "Yes" } },
  });
});

test("partitionAnswers splits missing, malformed, and valid ids", () => {
  const questions = { missing: noulQuestion, bad: choiceQuestion, ok: noulQuestion };
  expect(partitionAnswers(questions, null)).toEqual({
    valid: {},
    missing: ["missing", "bad", "ok"],
    malformed: [],
  });
  expect(
    partitionAnswers(questions, {
      bad: noulAnswer,
      ok: noulAnswer,
    }),
  ).toEqual({
    valid: { ok: noulAnswer },
    missing: ["missing"],
    malformed: ["bad"],
  });
});

test("scoreValue is the expected value; scoreLevel is not exported", () => {
  expect(scoreValue(scoreAnswer)).toBe(1.2);
  expect("scoreLevel" in answers).toBe(false);
});
