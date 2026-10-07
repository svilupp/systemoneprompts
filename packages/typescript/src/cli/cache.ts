import { join } from "node:path";
import { cacheStats, clearCache, defaultCacheDir } from "../dev/cache.js";
import { cloudflareCacheDir } from "../dev/cloudflare-cache.js";
import { openAICacheDir } from "../dev/openai-cache.js";
import { openRouterCacheDir } from "../openrouter.js";
import { loadDotEnv } from "./env.js";
import { fail } from "./io.js";

export async function runCache(
  action: string | undefined,
  options: { provider?: string; cacheRoot?: string; baseURL?: string } = {},
): Promise<void> {
  loadDotEnv();
  const provider = options.provider ?? "typesafe";
  if (
    provider !== "typesafe" &&
    provider !== "openai" &&
    provider !== "cloudflare" &&
    provider !== "openrouter"
  )
    fail('provider-value: provider must be "typesafe", "openai", "cloudflare", or "openrouter"');
  if (options.baseURL && provider === "typesafe")
    fail("--base-url is only used for Decisions cache scope");
  const dir =
    provider === "openrouter"
      ? openRouterCacheDir({ dir: options.cacheRoot, baseURL: options.baseURL })
      : provider === "cloudflare"
        ? cloudflareCacheDir({ dir: options.cacheRoot, baseURL: options.baseURL })
        : provider === "openai"
          ? openAICacheDir({ dir: options.cacheRoot, baseURL: options.baseURL })
          : options.cacheRoot
            ? join(options.cacheRoot, "cache")
            : defaultCacheDir();
  if (action === "clear") {
    await clearCache(dir);
    console.log(`cleared ${dir}`);
    return;
  }
  if (action === "stats" || action == null) {
    const stats = await cacheStats(dir);
    console.log(`dir      ${dir}`);
    console.log(`entries  ${stats.entries}`);
    for (const [model, count] of Object.entries(stats.models)) {
      console.log(`model    ${model}  ${count}`);
    }
    for (const row of stats.drift) {
      if (row.requested && row.requested !== row.reported) {
        console.log(`drift    ${row.requested} → ${row.reported}  ${row.count}`);
      }
    }
    return;
  }
  fail("systemoneprompts cache stats | clear");
}
