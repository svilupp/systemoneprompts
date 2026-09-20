import { describe, expect, test } from "bun:test";
import type { ChoiceResponse, Questions } from "../src/index.ts";
import {
  type RunManyItem,
  runMany,
  type SystemOneClient,
  walkTaxonomy,
} from "../src/patterns/index.ts";

const usage = { input_tokens: 1, output_tokens: 0 };

describe("runMany", () => {
  test("rejects invalid concurrency before calling the client", async () => {
    let calls = 0;
    const client: SystemOneClient = {
      systemOne: async () => {
        calls += 1;
        return { model: "test", answers: {}, usage };
      },
    };
    for (const concurrency of [NaN, Infinity, -1, 0, 1.5]) {
      await expect(runMany(client, { questions: {}, states: [{}], concurrency })).rejects.toThrow(
        "concurrency must be a positive integer",
      );
    }
    expect(calls).toBe(0);
  });

  test("a throwing result callback runs once and rejects the batch", async () => {
    let callbacks = 0;
    const client: SystemOneClient = {
      systemOne: async () => ({ model: "test", answers: {}, usage }),
    };
    await expect(
      runMany(client, {
        questions: {},
        states: [{}],
        onResult: () => {
          callbacks += 1;
          throw new Error("callback failed");
        },
      }),
    ).rejects.toThrow("callback failed");
    expect(callbacks).toBe(1);
  });

  test("preserves order, collects errors, and types answers from the questions", async () => {
    const client: SystemOneClient = {
      systemOne: async ({ state }) => {
        const n = (state as { n: number }).n;
        if (n === 2) throw new Error("boom");
        return { model: "jev-latest", answers: { ok: { type: "noul", noul: n } }, usage };
      },
    };
    const seen: number[] = [];
    const results = await runMany(client, {
      questions: { ok: { type: "noul", instructions: "ok?" } } as const satisfies Questions,
      states: [{ n: 1 }, { n: 2 }, { n: 3 }],
      concurrency: 2,
      onResult: (index) => seen.push(index),
    });
    expect(results).toHaveLength(3);
    expect(seen.sort()).toEqual([0, 1, 2]);
    const first = results[0];
    if (first === undefined || first instanceof Error) throw new Error("expected a result");
    const noul: number = first.answers.ok.noul; // typed, no cast
    expect(noul).toBe(1);
    expect(results[1]).toBeInstanceOf(Error);
    expect(results[2]).toMatchObject({ answers: { ok: { noul: 3 } } });
  });

  test("handles an empty batch", async () => {
    const client: SystemOneClient = {
      systemOne: async () => {
        throw new Error("should not be called");
      },
    };
    expect(await runMany(client, { questions: {}, states: [] })).toEqual([]);
  });

  test("asks each item's questions and preserves order", async () => {
    const seen: Array<{ state: unknown; questions: unknown }> = [];
    const client: SystemOneClient = {
      systemOne: async ({ state, questions }) => {
        seen.push({ state, questions });
        const id = (state as { id: number }).id;
        return { model: "test", answers: { id: { type: "noul", noul: id } }, usage };
      },
    };
    const q1: Questions = { a: { type: "noul", instructions: "a?" } };
    const q2: Questions = { b: { type: "noul", instructions: "b?" } };
    const items: readonly RunManyItem[] = [
      { state: { id: 1 }, questions: q1 },
      { state: { id: 2 }, questions: q2 },
    ];
    const results = await runMany(client, { items, concurrency: 2 });
    expect(results).toHaveLength(2);
    expect(results[0]).toMatchObject({ answers: { id: { noul: 1 } } });
    expect(results[1]).toMatchObject({ answers: { id: { noul: 2 } } });
    expect(seen).toHaveLength(2);
    expect(seen).toEqual(
      expect.arrayContaining([
        { state: { id: 1 }, questions: q1 },
        { state: { id: 2 }, questions: q2 },
      ]),
    );
  });

  test("rejects mixing items and states before calling the client", async () => {
    let calls = 0;
    const client: SystemOneClient = {
      systemOne: async () => {
        calls += 1;
        return { model: "test", answers: {}, usage };
      },
    };
    await expect(
      runMany(client, {
        questions: {},
        states: [{}],
        items: [{ state: {}, questions: {} }],
      } as never),
    ).rejects.toThrow("runMany accepts either items or states, not both");
    expect(calls).toBe(0);
  });

  test("rejects items mixed with questions, and shared options missing states", async () => {
    let calls = 0;
    const client: SystemOneClient = {
      systemOne: async () => {
        calls += 1;
        return { model: "test", answers: {}, usage };
      },
    };
    await expect(
      runMany(client, {
        items: [{ state: {}, questions: {} }],
        questions: {},
      } as never),
    ).rejects.toThrow("runMany accepts either items or states, not both");
    await expect(runMany(client, { questions: {} } as never)).rejects.toThrow(
      "runMany requires questions and states",
    );
    expect(calls).toBe(0);
  });

  test("handles an empty items batch", async () => {
    const client: SystemOneClient = {
      systemOne: async () => {
        throw new Error("should not be called");
      },
    };
    expect(await runMany(client, { items: [] })).toEqual([]);
  });
});

describe("walkTaxonomy", () => {
  test("rejects invalid beam widths before calling the client", async () => {
    let calls = 0;
    const client: SystemOneClient = {
      systemOne: async () => {
        calls += 1;
        throw new Error("unexpected request");
      },
    };
    for (const beamWidth of [NaN, Infinity, -1, 0, 1.5]) {
      await expect(
        walkTaxonomy(client, { state: {}, tree: { A: "a" }, beamWidth }),
      ).rejects.toThrow("beamWidth must be a positive integer");
    }
    expect(calls).toBe(0);
  });

  /** A client that always prefers the first label with probability 0.7. */
  const client: SystemOneClient = {
    systemOne: async ({ questions }) => {
      const step = questions.step as { criteria: Record<string, unknown> };
      const labels = Object.keys(step.criteria);
      const probabilities = Object.fromEntries(
        labels.map((label, i) => [label, i === 0 ? 0.7 : 0.3 / Math.max(1, labels.length - 1)]),
      );
      const answer: ChoiceResponse = {
        type: "choice",
        choice: labels[0]!,
        confidence: 0.7,
        probabilities,
      };
      return { model: "jev-latest", answers: { step: answer }, usage };
    },
  };

  test("walks children and keeps a beam", async () => {
    const paths = await walkTaxonomy(client, {
      state: { title: "bike bottle" },
      instructions: "Which department?",
      beamWidth: 2,
      tree: {
        Sporting: { Cycling: { Bottles: "Bike bottles" } },
        Home: { Drinkware: { Bottles: "Kitchen bottles" } },
      },
    });
    expect(paths).toHaveLength(2);
    expect(paths[0]?.path).toEqual(["Sporting", "Cycling", "Bottles"]);
    expect(paths[0]?.probability).toBeCloseTo(0.7 ** 3); // 0.7 at each of the three levels
    expect(paths[1]?.path).toEqual(["Home", "Drinkware", "Bottles"]);
    expect(paths[1]?.probability).toBeCloseTo(0.3 * 0.7 * 0.7);
  });

  test("explicit nodes contribute their description and children", async () => {
    let criteriaSeen: unknown;
    const spy: SystemOneClient = {
      systemOne: async (request) => {
        criteriaSeen ??= (request.questions.step as { criteria: unknown }).criteria;
        return client.systemOne(request);
      },
    };
    const paths = await walkTaxonomy(spy, {
      state: {},
      tree: {
        A: { description: "leaf a" },
        B: { description: "branch b", children: { B1: "leaf b1" } },
      },
    });
    expect(criteriaSeen).toEqual({ A: "leaf a", B: { B1: "leaf b1" } });
    expect(paths).toEqual([{ path: ["A"], probability: 0.7 }]);
  });
});
