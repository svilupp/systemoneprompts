import { describe, expect, test } from "bun:test";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { emitRequiredState } from "../src/generate/types.ts";
import { createStateAssert, type StateAssert } from "../src/index.ts";
import { root, tsc } from "./helpers.ts";

describe("RequiredState generation", () => {
  test("emits nested indexed paths as nested array elements", async () => {
    const requires = {
      "matrix[0][0]": "number",
      "matrix[0][1]": "number",
    } as const;
    const emitted = emitRequiredState(requires);
    expect(emitted).toContain("matrix: number[][];");

    const dir = await mkdtemp(join(tmpdir(), "jev-state-generation-"));
    await writeFile(
      join(dir, "state.ts"),
      `import type { JsonValue } from "systemoneprompts";
${emitted}
const state: RequiredState = { matrix: [[1, 2]] };
const value: number = state.matrix[0]![1]!;
void value;
`,
    );
    await writeFile(
      join(dir, "tsconfig.json"),
      JSON.stringify(
        {
          compilerOptions: {
            target: "ES2022",
            module: "NodeNext",
            moduleResolution: "NodeNext",
            strict: true,
            skipLibCheck: true,
            noEmit: true,
            allowImportingTsExtensions: true,
            types: ["node"],
            typeRoots: [join(root, "node_modules/@types")],
            baseUrl: ".",
            paths: { systemoneprompts: [join(root, "src/index.ts")] },
          },
          include: ["./*.ts"],
        },
        null,
        2,
      ),
    );
    const result = tsc(["-p", join(dir, "tsconfig.json")]);
    if (result.exitCode !== 0) throw new Error(result.output);
  });

  test("preserves nested constraints when parent declarations change order", () => {
    const objectFirst = emitRequiredState({
      profile: "object",
      "profile.name": "string",
    });
    const objectLast = emitRequiredState({
      "profile.name": "string",
      profile: "object",
    });
    expect(objectFirst).toBe(objectLast);
    expect(objectFirst).toContain("name: string;");

    const arrayFirst = emitRequiredState({
      items: "array",
      "items[0].id": "string",
    });
    const arrayLast = emitRequiredState({
      "items[0].id": "string",
      items: "array",
    });
    expect(arrayFirst).toBe(arrayLast);
    expect(arrayFirst).toContain("items: {\n    id: string;\n    [k: string]: JsonValue;\n  }[];");
    expect(emitRequiredState({ "messages[].text": "string" })).toBe(
      emitRequiredState({ "messages[0].text": "string" }),
    );

    const existsFirst = emitRequiredState({
      metadata: "exists",
      "metadata.source": "string",
    });
    const existsLast = emitRequiredState({
      "metadata.source": "string",
      metadata: "exists",
    });
    expect(existsFirst).toBe(existsLast);
    expect(existsFirst).toContain("source: string;");
  });

  test("asserts nested indexed paths without copying state", () => {
    const requires = { "matrix[0][0]": "number" } as const;
    const assertState: StateAssert = createStateAssert(requires);
    const state = { matrix: [[7]] };

    assertState(state);
    expect(state).toEqual({ matrix: [[7]] });
    expect(() => assertState({ matrix: [["7"]] })).toThrow(
      "matrix[0][0]: expected number, got string",
    );
  });
});
