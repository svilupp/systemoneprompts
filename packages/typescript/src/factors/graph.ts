import { type Diagnostic, diagnostic, type SourceLocation } from "../definition/diagnostics.js";
import type { FactorDef } from "./schema.js";
import { referencedIds } from "./schema.js";

export function topoSortFactors(
  factors: Record<string, FactorDef>,
  locateFactor: (id: string) => SourceLocation,
): { order: string[]; diagnostics: Diagnostic[] } {
  const diagnostics: Diagnostic[] = [];
  const factorIds = new Set(Object.keys(factors));
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const order: string[] = [];
  const stack: string[] = [];

  const visit = (id: string): void => {
    if (visited.has(id)) return;
    if (visiting.has(id)) {
      const cycleStart = stack.indexOf(id);
      const cycle = [...stack.slice(cycleStart), id];
      diagnostics.push(
        diagnostic("error", "cycle", `cycle: ${cycle.join(" → ")}`, locateFactor(id)),
      );
      return;
    }
    visiting.add(id);
    stack.push(id);
    if (Object.hasOwn(factors, id)) {
      const factor = factors[id]!;
      for (const ref of referencedIds(factor)) {
        if (!factorIds.has(ref)) continue;
        visit(ref);
      }
    }
    stack.pop();
    visiting.delete(id);
    visited.add(id);
    order.push(id);
  };

  for (const id of Object.keys(factors)) {
    visit(id);
  }

  return { order, diagnostics };
}
