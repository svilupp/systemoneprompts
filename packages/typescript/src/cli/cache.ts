import { join } from "node:path";
import { cacheStats, clearCache, defaultCacheDir } from "../dev/cache.js";
import { openAICacheDir } from "../dev/openai-cache.js";
import { fail } from "./io.js";

export async function runCache(
  action: string | undefined,
  options: { provider?: string; cacheRoot?: string; baseURL?: string } = {},
): Promise<void> {
  const provider = options.provider ?? "typesafe";
  if (provider !== "typesafe" && provider !== "openai")
    fail('provider-value: provider must be "typesafe" or "openai"');
  if (options.baseURL && provider !== "openai")
    fail("--base-url is only used for OpenAI cache scope");
  const dir =
    provider === "openai"
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
