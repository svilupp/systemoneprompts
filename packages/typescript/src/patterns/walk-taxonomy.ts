import { isPlainObject } from "../json.js";
import type { ChoiceResponse, EntryType, Questions } from "../native.js";
import { positiveInteger } from "./options.js";
import type { SystemOneClient } from "./run-many.js";

/** An explicit node: a description for this label plus optional children. */
export interface TaxonomyNode {
  description?: EntryType;
  children?: TaxonomyTree;
}

/**
 * Labels mapped to a leaf description (string), an explicit node, or a nested tree.
 * A nested tree whose own labels are literally `description` / `children` must be
 * written as an explicit `TaxonomyNode` to avoid being read as one.
 */
export interface TaxonomyTree {
  [label: string]: string | TaxonomyNode | TaxonomyTree;
}

export interface WalkTaxonomyOptions {
  state: unknown;
  /** Instructions reused at every level; the criteria are the current node's children. */
  instructions?: EntryType;
  tree: TaxonomyTree;
  /** Paths kept alive at each level, ranked by cumulative probability. Default 1. */
  beamWidth?: number;
  model?: string;
}

export interface TaxonomyPath {
  path: string[];
  /** Product of the Choice probabilities along the path. */
  probability: number;
}

interface BeamItem extends TaxonomyPath {
  node: TaxonomyTree;
}

const STEP = "step";

/**
 * Hierarchical Choice: at each level the criteria are the current node's children with
 * their subtrees as descriptions, so the model sees what each branch leads to. Returns the
 * best complete paths found within the beam, most probable first. Beam pruning
 * is approximate: it can discard a branch containing a globally better leaf.
 */
export async function walkTaxonomy(
  client: SystemOneClient,
  opts: WalkTaxonomyOptions,
): Promise<TaxonomyPath[]> {
  const beamWidth = positiveInteger("beamWidth", opts.beamWidth ?? 1);
  let beam: BeamItem[] = [{ path: [], probability: 1, node: opts.tree }];
  const finished: TaxonomyPath[] = [];

  while (beam.length > 0) {
    const expanded: BeamItem[] = [];
    for (const item of beam) {
      const labels = Object.keys(item.node);
      if (labels.length === 0) {
        finished.push({ path: item.path, probability: item.probability });
        continue;
      }

      const criteria = Object.fromEntries(
        labels.map((label) => [label, subtreeDescription(item.node[label]!)]),
      );
      const questions: Questions = {
        [STEP]: {
          type: "choice",
          ...(opts.instructions !== undefined ? { instructions: opts.instructions } : {}),
          criteria,
        },
      };
      const response = await client.systemOne({ state: opts.state, questions, model: opts.model });
      const { probabilities } = response.answers[STEP] as ChoiceResponse;

      for (const label of labels) {
        expanded.push({
          path: [...item.path, label],
          probability: item.probability * (probabilities[label] ?? 0),
          node: childrenOf(item.node[label]!),
        });
      }
    }

    expanded.sort((a, b) => b.probability - a.probability);
    const continuing: BeamItem[] = [];
    for (const item of expanded) {
      if (Object.keys(item.node).length === 0) {
        finished.push({ path: item.path, probability: item.probability });
      } else {
        continuing.push(item);
      }
    }
    beam = continuing.slice(0, beamWidth);
  }

  finished.sort((a, b) => b.probability - a.probability);
  return finished.slice(0, beamWidth);
}

function childrenOf(value: string | TaxonomyNode | TaxonomyTree): TaxonomyTree {
  if (typeof value === "string") return {};
  if (isNode(value)) return value.children ?? {};
  return value;
}

/** A leaf's description, or a nested object mirroring the subtree so the model sees where a branch leads. */
function subtreeDescription(value: string | TaxonomyNode | TaxonomyTree): EntryType {
  if (typeof value === "string") return value;
  if (isNode(value)) {
    if (value.children && Object.keys(value.children).length > 0) {
      return treeDescription(value.children);
    }
    return value.description ?? null;
  }
  return treeDescription(value);
}

function treeDescription(tree: TaxonomyTree): EntryType {
  return Object.fromEntries(
    Object.entries(tree).map(([label, child]) => [label, subtreeDescription(child)]),
  ) as EntryType;
}

function isNode(value: unknown): value is TaxonomyNode {
  return (
    isPlainObject(value) &&
    (Object.hasOwn(value, "description") || Object.hasOwn(value, "children"))
  );
}
