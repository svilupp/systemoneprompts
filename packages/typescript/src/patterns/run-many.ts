import type { Questions, SystemOneResult } from "../native.js";
import { positiveInteger } from "./options.js";

/**
 * The slice of `TypeSafeClient` the patterns need. Any object with a compatible
 * `systemOne` works, which keeps the helpers testable without the network.
 */
export interface SystemOneClient {
  systemOne(request: {
    state: unknown;
    questions: Questions;
    model?: string;
  }): Promise<SystemOneResult<Questions>>;
}

export interface RunManyItem<Q extends Questions = Questions> {
  state: unknown;
  questions: Q;
  model?: string;
}

type RunManyShared<Q extends Questions> = {
  model?: string;
  /** Maximum in-flight requests. Default 4. */
  concurrency?: number;
  /** Called once as each state settles, in completion order. A thrown callback rejects the batch. */
  onResult?: (index: number, result: SystemOneResult<Q> | Error) => void;
};

export type RunManyOptions<Q extends Questions> =
  | (RunManyShared<Q> & {
      questions: Q;
      states: readonly unknown[];
      items?: never;
    })
  | (RunManyShared<Q> & {
      items: readonly RunManyItem<Q>[];
      questions?: never;
      states?: never;
    });

/**
 * Ask questions about many states with bounded concurrency.
 * Pass shared `questions` + `states`, or per-item `{ state, questions }`.
 * Results keep input order; a failed call yields its `Error` instead of aborting the batch.
 */
export async function runMany<Q extends Questions>(
  client: SystemOneClient,
  opts: RunManyOptions<Q>,
): Promise<Array<SystemOneResult<Q> | Error>> {
  const concurrency = positiveInteger("concurrency", opts.concurrency ?? 4);
  const jobs = jobsOf(opts);
  const results: Array<SystemOneResult<Q> | Error> = new Array(jobs.length);
  let next = 0;

  const worker = async () => {
    while (next < jobs.length) {
      const index = next++;
      const job = jobs[index]!;
      try {
        const result = (await client.systemOne({
          state: job.state,
          questions: job.questions,
          model: job.model,
        })) as SystemOneResult<Q>;
        results[index] = result;
      } catch (error) {
        const err = error instanceof Error ? error : new Error(String(error));
        results[index] = err;
      }
      opts.onResult?.(index, results[index]!);
    }
  };

  await Promise.all(Array.from({ length: Math.min(concurrency, jobs.length) }, () => worker()));
  return results;
}

function jobsOf<Q extends Questions>(opts: RunManyOptions<Q>): RunManyItem<Q>[] {
  const { items, states, questions, model } = opts as {
    items?: readonly RunManyItem<Q>[];
    states?: readonly unknown[];
    questions?: Q;
    model?: string;
  };
  if (items !== undefined && (states !== undefined || questions !== undefined)) {
    throw new Error("runMany accepts either items or states, not both");
  }
  if (items !== undefined) {
    return items.map((item) => ({
      state: item.state,
      questions: item.questions,
      model: item.model ?? model,
    }));
  }
  if (questions === undefined || states === undefined) {
    throw new Error("runMany requires questions and states");
  }
  return states.map((state) => ({ state, questions, model }));
}
