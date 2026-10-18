// Parse → check → derive → generate. Everything else in the package is tooling around these.

export {
  boxValue,
  choiceLabel,
  isAnswerForQuestion,
  isAnswerShape,
  isBoxCoordinates,
  noulValue,
  partitionAnswers,
  scoreValue,
  wireQuestions,
} from "./answers.js";
export { assetReferences, IMAGE_OPT_IN_HEADER, validateAssets } from "./assets.js";
export {
  DEFAULT_BASE_URL,
  DEFAULT_TIMEOUT_MS,
  type SystemOneCallOptions,
  TypeSafeClient,
  TypeSafeClientError,
  type TypeSafeClientOptions,
  TypeSafeHttpError,
  TypeSafeRateLimitError,
  TypeSafeTimeoutError,
} from "./client.js";
export {
  CLOUDFLARE_MODEL,
  cloudflareRunUrl,
  createCloudflareFetch,
} from "./cloudflare.js";
export {
  CloudflareDecisionsClient,
  type CloudflareDecisionsClientOptions,
  CloudflareDecisionsError,
} from "./cloudflare-decisions.js";
export { checkDefinition } from "./definition/check.js";
export {
  type Diagnostic,
  type DiagnosticSeverity,
  errorsOf,
  formatDiagnostic,
  formatLocation,
  hasErrors,
  type SourceLocation,
  SystemOnePromptsError,
} from "./definition/diagnostics.js";
export { loadDefinition, type ParseOptions, parseDefinition } from "./definition/parse.js";
export type {
  Definition,
  DefinitionData,
  DefinitionMeta,
  DefinitionSource,
  FactorDefinitions,
} from "./definition/schema.js";
export {
  type AnswersFor,
  createFactorEvaluator,
  isKnownNativeAnswer,
  NOUL_CUTOFF,
} from "./factors/evaluate.js";
export type { Comparator, FactorDef, FactorTable } from "./factors/schema.js";
export {
  type AssetDeclaration,
  type AssetDeclarations,
  type AssetLoadOptions,
  type AssetManifest,
  imageAsset,
  loadAssets,
  loadPackagedAssets,
} from "./file-assets.js";
export {
  emitGenerated,
  type GenerateOptions,
  generate,
  generateFile,
} from "./generate/generate.js";
export { DEFAULT_MODEL, readEnvModel, resolveModel } from "./model.js";
export type {
  Assets,
  BoxCoordinates,
  BoxQuestion,
  BoxResponse,
  ChoiceCriteria,
  ChoiceQuestion,
  ChoiceResponse,
  Description,
  EntryType,
  Fetch,
  ImageAsset,
  JsonValue,
  NoulQuestion,
  NoulResponse,
  Question,
  Questions,
  ResultFor,
  ScoreCriteria,
  ScoreLegend,
  ScoreOf,
  ScoreQuestion,
  ScoreResponse,
  SystemOneRequest,
  SystemOneResult,
  Usage,
} from "./native.js";
export {
  OpenAIDecisionsClient,
  type OpenAIDecisionsClientOptions,
  OpenAIDecisionsError,
} from "./openai-decisions.js";
export { QUESTION_TYPES, type QuestionType } from "./questions/schema.js";
export {
  createStateAssert,
  REQUIREMENT_TYPES,
  type Requirements,
  type RequirementType,
  type StateAssert,
} from "./state/requirements.js";
