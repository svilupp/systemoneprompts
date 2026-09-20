/** TypeSafe default when neither the TOML nor the call pins a model. */
export const DEFAULT_MODEL = "jev-latest";

/**
 * Resolve the model for a live call.
 * Later non-empty arguments win: env/default → TOML `model` → call-site override.
 */
export function resolveModel(...candidates: Array<string | undefined | null>): string {
  let resolved = DEFAULT_MODEL;
  for (const candidate of candidates) {
    if (typeof candidate !== "string") continue;
    const trimmed = candidate.trim();
    if (trimmed !== "") resolved = trimmed;
  }
  return resolved;
}

export function readEnvModel(
  env: Record<string, string | undefined> = process.env,
): string | undefined {
  const model = env.TYPESAFE_MODEL;
  return model?.trim() ? model : env.TYPESAFE_DEFAULT_MODEL;
}
