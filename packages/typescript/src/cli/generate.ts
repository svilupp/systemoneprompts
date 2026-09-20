import { mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { checkDefinition } from "../definition/check.js";
import { hasErrors, SystemOnePromptsError } from "../definition/diagnostics.js";
import { parseDefinition } from "../definition/parse.js";
import type { Definition } from "../definition/schema.js";
import { emitGenerated } from "../generate/generate.js";
import { fail, printDiagnostics, readText } from "./io.js";

export async function runGenerate(
  files: string[],
  options: { out?: string; check?: boolean },
): Promise<void> {
  if (files.length === 0) fail("systemoneprompts generate <files...> [--out dir] [--check]");

  const outputPaths = new Map<string, string[]>();
  for (const file of files) {
    if (!/\.toml$/i.test(file)) {
      console.error(`error: ${file}: source file must have a .toml extension`);
      process.exit(1);
    }
    const outPath = outputPath(file, options.out);
    const resolved = resolve(outPath);
    outputPaths.set(resolved, [...(outputPaths.get(resolved) ?? []), file]);
    if (resolve(file) === resolved) {
      console.error(`error: refusing to overwrite source file ${file}`);
      process.exit(1);
    }
  }
  const duplicates = [...outputPaths.entries()].filter(([, sources]) => sources.length > 1);
  if (duplicates.length > 0) {
    for (const [outPath, sources] of duplicates) {
      console.error(`error: duplicate output path ${outPath} for ${sources.join(", ")}`);
    }
    process.exit(1);
  }

  let failed = 0;
  for (const file of files) {
    let def: Definition;
    try {
      const source = await readText(file);
      def = parseDefinition(source, { filename: file });
    } catch (error) {
      failed += 1;
      if (error instanceof SystemOnePromptsError) printDiagnostics(error.diagnostics);
      else
        console.error(`error: ${file}: ${error instanceof Error ? error.message : String(error)}`);
      continue;
    }

    const diagnostics = checkDefinition(def);
    printDiagnostics(diagnostics);
    if (hasErrors(diagnostics)) {
      failed += 1;
      continue;
    }
    const generated = emitGenerated(def, file);
    const outPath = outputPath(file, options.out);
    if (options.check) {
      let existing: string | undefined;
      try {
        existing = await readFile(outPath, "utf8");
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") {
          console.error(`missing generated file: ${outPath}`);
        } else {
          console.error(
            `error: ${outPath}: ${error instanceof Error ? error.message : String(error)}`,
          );
        }
        failed += 1;
        continue;
      }
      if (existing !== generated) {
        console.error(`stale generated file: ${outPath}`);
        failed += 1;
      }
      continue;
    }
    try {
      await mkdir(dirname(outPath), { recursive: true });
      await writeFile(outPath, generated);
      console.log(outPath);
    } catch (error) {
      failed += 1;
      console.error(`error: ${outPath}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  if (failed > 0) process.exit(1);
}

function outputPath(file: string, outDir?: string): string {
  const name = basename(file).replace(/\.toml$/i, ".generated.ts");
  return join(outDir ?? dirname(file), name);
}
