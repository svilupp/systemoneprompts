/** JSON-compatible value used for state, instructions, criteria, and generated types. */
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

/** Text, a JSON object or array, or `null` for state, instructions, and criteria. */
export type EntryType = string | { [key: string]: JsonValue } | JsonValue[] | null;

/** A criterion description; `null` leaves the label undescribed. */
export type Description = EntryType;

/** A yes/no question with optional descriptions for either outcome. */
export interface NoulQuestion {
  type: "noul";
  instructions?: EntryType;
  criteria?: {
    true?: EntryType;
    false?: EntryType;
  } | null;
}

/** Labels mapped to descriptions, or `null` for undescribed labels. */
export type ChoiceCriteria = { [label: string]: Description };

/** A question that selects between named alternatives. */
export interface ChoiceQuestion<T extends ChoiceCriteria = ChoiceCriteria> {
  type: "choice";
  instructions?: EntryType;
  criteria: T;
}

/** At least two descriptions indexed by score from zero; `null` leaves a score undescribed. */
export type ScoreCriteria = readonly [EntryType, EntryType, ...EntryType[]];

/** A question that assigns a score using an ordered rubric. */
export interface ScoreQuestion<T extends ScoreCriteria = ScoreCriteria> {
  type: "score";
  instructions?: EntryType;
  criteria: T;
}

/** A question identified by its `type` field. */
export type Question = NoulQuestion | ScoreQuestion | ChoiceQuestion;

/** Questions keyed by the names used to identify their answers. */
export interface Questions {
  [name: string]: Question;
}

/** A yes/no answer. */
export interface NoulResponse {
  readonly type: "noul";
  readonly noul: number;
}

/** A selected label and its probabilities. */
export interface ChoiceResponse<T extends ChoiceCriteria = ChoiceCriteria> {
  readonly type: "choice";
  readonly choice: keyof T & string;
  readonly confidence: number;
  readonly probabilities: { readonly [label in keyof T]: number };
}

/** Score keys inferred from the rubric; a fixed-length tuple yields its indices, otherwise `number`. */
export type ScoreOf<T extends ScoreCriteria> = number extends T["length"]
  ? number
  : Extract<keyof T, `${number}`>;

/** Rubric descriptions keyed by score. */
export type ScoreLegend<T extends ScoreCriteria> = { readonly [score in ScoreOf<T>]: T[score] };

/** An expected score with its rubric and probabilities. */
export interface ScoreResponse<T extends ScoreCriteria = ScoreCriteria> {
  readonly type: "score";
  readonly score: number;
  readonly confidence: number;
  readonly legend: ScoreLegend<T>;
  readonly probabilities: { readonly [score in ScoreOf<T>]: number };
}

/** The answer type for a question, preserving its criteria keys. */
export type ResultFor<T extends Question> = T extends NoulQuestion
  ? NoulResponse
  : T extends ScoreQuestion<infer S>
    ? ScoreResponse<S>
    : T extends ChoiceQuestion<infer E>
      ? ChoiceResponse<E>
      : never;

/** Token usage for a request. */
export interface Usage {
  readonly input_tokens: number;
  readonly output_tokens: number;
}

/** Answers keyed by question name, with model and usage metadata. */
export interface SystemOneResult<Q extends Questions> {
  readonly model: string;
  readonly answers: { readonly [K in keyof Q]: ResultFor<Q[K]> };
  readonly usage: Usage;
}

/** State and named questions for `systemOne`. */
export interface SystemOneRequest<Q extends Questions = Questions> {
  state: unknown;
  questions: Q;
  model?: string;
}

/** HTTP fetch compatible with the global `fetch`. */
export type Fetch = (input: string, init?: RequestInit) => Promise<Response>;
