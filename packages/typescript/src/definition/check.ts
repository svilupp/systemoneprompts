import { topoSortFactors } from "../factors/graph.js";
import { validatePrimitiveRefs } from "../factors/schema.js";
import { lintBackticks } from "../questions/references.js";
import { questionInfos } from "../questions/schema.js";
import { checkRequirementConflicts } from "../state/requirements.js";
import type { Diagnostic } from "./diagnostics.js";
import { locate } from "./locate.js";
import type { Definition } from "./schema.js";

/**
 * Every diagnostic for a definition: the structural ones collected while parsing,
 * plus cross-cutting checks — factor references and primitive compatibility,
 * cycles, `[requires]` path conflicts, and the backtick lint.
 */
export function checkDefinition(def: Definition): Diagnostic[] {
  const index = def.source.index;
  const diagnostics: Diagnostic[] = [...def.diagnostics];

  diagnostics.push(...checkRequirementConflicts(def.requires, index));

  const infos = questionInfos(def.questions);
  const factorIds = new Set(Object.keys(def.factors));
  for (const [id, factor] of Object.entries(def.factors)) {
    diagnostics.push(
      ...validatePrimitiveRefs(
        id,
        factor,
        infos,
        factorIds,
        locate(index, { section: "factors", key: id, table: "factors" }),
      ),
    );
  }

  const sorted = topoSortFactors(def.factors, (id) =>
    locate(index, { section: "factors", key: id }),
  );
  diagnostics.push(...sorted.diagnostics);
  diagnostics.push(...lintBackticks(def.questions, def.requires, index));

  return diagnostics;
}
