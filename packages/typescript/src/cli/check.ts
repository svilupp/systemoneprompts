import { checkDefinition } from "../definition/check.js";
import { SystemOnePromptsError } from "../definition/diagnostics.js";
import { parseDefinition } from "../definition/parse.js";
import { loadAssets } from "../file-assets.js";
import { fail, printDiagnostics, readText } from "./io.js";

export async function runCheck(files: string[], strict: boolean): Promise<void> {
  if (files.length === 0) fail("systemoneprompts check <files...> [--strict]");
  let errors = 0;
  for (const file of files) {
    try {
      const source = await readText(file);
      const def = parseDefinition(source, { filename: file });
      const diagnostics = checkDefinition(def);
      errors += printDiagnostics(diagnostics, strict);
      if (!diagnostics.some((d) => d.severity === "error"))
        await loadAssets(def, { allowUnboundRuntime: true });
    } catch (error) {
      if (error instanceof SystemOnePromptsError) {
        errors += printDiagnostics(error.diagnostics, strict);
      } else {
        errors += 1;
        console.error(`error: ${file}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
  }
  if (errors > 0) process.exit(1);
}
