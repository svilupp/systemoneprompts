import { createHash } from "node:crypto";
import { join } from "node:path";

export function openRouterBaseURL(
  value = process.env.OPENROUTER_BASE_URL?.trim() || "https://openrouter.ai/api/alpha",
): string {
  const normalized = value
    .trim()
    .replace(/\/+$/, "")
    .replace(/\/decisions$/, "");
  let url: URL;
  try {
    url = new URL(normalized);
  } catch {
    throw new Error("base_url must be an HTTP(S) URL without credentials, query, or fragment");
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    throw new Error("base_url must be an HTTP(S) URL without credentials, query, or fragment");
  return normalized;
}

export function openRouterCacheDir(options: { dir?: string; baseURL?: string } = {}): string {
  return join(
    options.dir ?? join(process.cwd(), ".systemoneprompts"),
    "providers",
    "openrouter-decisions",
    "v1",
    createHash("sha256").update(openRouterBaseURL(options.baseURL)).digest("hex"),
    "cache",
  );
}
