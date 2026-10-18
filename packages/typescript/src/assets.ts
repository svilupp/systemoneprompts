import { imageAsset, MAX_IMAGE_BYTES } from "./image-bytes.js";

export { MAX_IMAGE_BYTES } from "./image-bytes.js";

import { isPlainObject } from "./json.js";
import type { Assets } from "./native.js";

export const IMAGE_OPT_IN_HEADER = "TypeSafe-Danger-Zone-Images";
export const MAX_REQUEST_BYTES = 32 * 1024 * 1024;

/** Find reserved references in string values only; object keys remain literal. */
export function assetReferences(value: unknown): Set<string> {
  const refs = new Set<string>();
  const visit = (item: unknown): void => {
    if (typeof item === "string") {
      for (const match of item.matchAll(/<asset:([^<>]+)>/g)) refs.add(match[1]!);
    } else if (Array.isArray(item)) item.forEach(visit);
    else if (isPlainObject(item)) Object.values(item).forEach(visit);
  };
  visit(value);
  return refs;
}

/** Validate the exact JSON/base64 wire asset map without changing its bytes. */
export function validateAssets(value: unknown): asserts value is Assets {
  if (!isPlainObject(value)) throw new Error("assets must be an object keyed by asset ID");
  let total = 0;
  let referenceBytes = 0;
  for (const [id, asset] of Object.entries(value)) {
    const size = Buffer.byteLength(id);
    if (!id.trim() || size > 1024)
      throw new Error(
        `invalid asset reference ${JSON.stringify(id)}: must be nonblank and at most 1024 UTF-8 bytes`,
      );
    referenceBytes += size;
    if (referenceBytes > 65536) throw new Error("asset references exceed 65536 UTF-8 bytes");
    if (
      !isPlainObject(asset) ||
      Object.keys(asset).sort().join(",") !== "data_base64,format,type" ||
      asset.type !== "image" ||
      !["png", "jpg", "jpeg"].includes(String(asset.format)) ||
      typeof asset.data_base64 !== "string"
    )
      throw new Error(
        `asset ${JSON.stringify(id)} must contain exactly type=image, format=png|jpg|jpeg, data_base64`,
      );
    const encoded = asset.data_base64;
    if (
      !encoded ||
      encoded.length > 4 * Math.ceil(MAX_IMAGE_BYTES / 3) ||
      encoded.length % 4 !== 0 ||
      !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)
    )
      throw new Error(`asset ${JSON.stringify(id)} has invalid base64`);
    const bytes = Buffer.from(encoded, "base64");
    if (bytes.toString("base64") !== encoded)
      throw new Error(`asset ${JSON.stringify(id)} has noncanonical base64`);
    if (bytes.length > MAX_IMAGE_BYTES)
      throw new Error(`asset ${JSON.stringify(id)} exceeds 16 MiB`);
    const decoded = imageAsset(bytes);
    if (decoded.format !== (asset.format === "jpeg" ? "jpg" : asset.format))
      throw new Error(
        `asset ${JSON.stringify(id)} bytes do not match declared format ${String(asset.format)}`,
      );
    total += bytes.length;
  }
  if (total > MAX_REQUEST_BYTES) throw new Error("assets exceed 32 MiB aggregate bytes");
}

export function hasVisionFeatures(request: { questions: unknown; assets?: unknown }): boolean {
  return (
    (request.assets !== undefined &&
      !(isPlainObject(request.assets) && Object.keys(request.assets).length === 0)) ||
    (isPlainObject(request.questions) &&
      Object.values(request.questions).some((q) => isPlainObject(q) && q.type === "box"))
  );
}

/** Collect actual native matches without replacing values or matching object keys. */
export function usedAssetReferences(value: unknown, references: readonly string[]): Set<string> {
  const used = new Set<string>();
  const visit = (item: unknown): void => {
    if (typeof item === "string") {
      if (references.includes(item)) {
        used.add(item);
        return;
      }
      let cursor = 0;
      while (cursor < item.length) {
        let first = item.length;
        let matches: string[] = [];
        for (const ref of references) {
          const position = item.indexOf(ref, cursor);
          if (position < 0 || position > first) continue;
          if (position < first) {
            first = position;
            matches = [];
          }
          matches.push(ref);
        }
        if (!matches.length) break;
        if (matches.length > 1)
          throw new Error(
            `ambiguous overlapping asset references at ${JSON.stringify(item.slice(first))}; use distinct references`,
          );
        const ref = matches[0]!;
        used.add(ref);
        cursor = first + ref.length;
      }
    } else if (Array.isArray(item)) item.forEach(visit);
    else if (isPlainObject(item)) Object.values(item).forEach(visit);
  };
  visit(value);
  return used;
}

export function validateAssetReferences(state: unknown, questions: unknown, assets?: Assets): void {
  const values = [
    state,
    ...(isPlainObject(questions)
      ? Object.values(questions).flatMap((q) =>
          isPlainObject(q) ? [q.instructions, q.criteria] : [],
        )
      : []),
  ];
  const refs = assetReferences(values);
  for (const id of refs)
    if (!assets || (!Object.hasOwn(assets, id) && !Object.hasOwn(assets, `<asset:${id}>`)))
      throw new Error(`missing asset ${JSON.stringify(id)} referenced by <asset:${id}>`);
  const used = usedAssetReferences(values, Object.keys(assets ?? {}));
  for (const id of Object.keys(assets ?? {}))
    if (!used.has(id)) throw new Error(`unused asset ${JSON.stringify(id)}`);
}

export function validateVisionRequest(
  request: { state: unknown; questions: unknown; assets?: unknown },
  headers: RequestInit["headers"],
  provider = "typesafe",
): void {
  if (hasVisionFeatures(request)) {
    if (provider !== "typesafe")
      throw new Error(`image assets and Box questions are unsupported by ${provider}`);
    if (new Headers(headers).get(IMAGE_OPT_IN_HEADER) !== "true")
      throw new Error(`${IMAGE_OPT_IN_HEADER}: true is required for image assets or Box questions`);
  }
  if (request.assets !== undefined) validateAssets(request.assets);
  validateAssetReferences(request.state, request.questions, request.assets as Assets | undefined);
  if (hasVisionFeatures(request) && Buffer.byteLength(JSON.stringify(request)) > MAX_REQUEST_BYTES)
    throw new Error("image request exceeds 32 MiB JSON bytes");
}
