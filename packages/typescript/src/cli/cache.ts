import { cacheStats, clearCache, defaultCacheDir } from "../dev/cache.js";
import { fail } from "./io.js";

export async function runCache(action: string | undefined): Promise<void> {
  const dir = defaultCacheDir();
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
