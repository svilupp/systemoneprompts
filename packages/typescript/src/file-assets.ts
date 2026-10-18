import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { assetReferences, MAX_IMAGE_BYTES, validateAssets } from "./assets.js";
import { formatLocation } from "./definition/diagnostics.js";
import { locate } from "./definition/locate.js";
import type { Definition } from "./definition/schema.js";
import { imageAsset } from "./image-bytes.js";

export { imageAsset } from "./image-bytes.js";

import { canonicalJson } from "./json.js";
import type { Assets } from "./native.js";

export type AssetDeclaration = { path: string; runtime?: never } | { runtime: true; path?: never };
export type AssetDeclarations = Record<string, AssetDeclaration>;
export interface AssetManifest {
  version: 1;
  assets: Record<string, { path: string; sha256: string }>;
}
export interface AssetLoadOptions {
  baseDir?: string;
  /** Declared runtime slots use logical IDs; undeclared keys are raw native references. */
  runtimeAssets?: Assets;
  /** For definition check/generation, which do not bind runtime slots. */
  allowUnboundRuntime?: boolean;
}

/** Convert managed IDs once, where bindings become native reference keys. */
function nativeAssets(assets: Assets, managedIds: readonly string[]): Assets {
  const result: Assets = Object.assign(Object.create(null), assets);
  for (const id of managedIds) {
    if (!Object.hasOwn(assets, id)) continue;
    const token = `<asset:${id}>`;
    if (Object.hasOwn(assets, token))
      throw new Error(
        `asset ${JSON.stringify(id)} collides with native reference ${JSON.stringify(token)}`,
      );
    delete result[id];
    result[token] = assets[id]!;
  }
  validateAssets(result);
  return result;
}

/** File IO is explicit; parsed definitions never read or resolve asset files implicitly. */
export async function loadAssets(def: Definition, options: AssetLoadOptions = {}): Promise<Assets> {
  const runtime = options.runtimeAssets ?? {};
  validateAssets(runtime);
  const assets: Assets = Object.assign(Object.create(null), runtime);
  const base = options.baseDir !== undefined ? resolve(options.baseDir) : def.source.baseDir;
  for (const [id, declaration] of Object.entries(def.assets)) {
    const sourceLocation =
      formatLocation(
        locate(def.source.index, { table: `assets.${id}`, section: "assets", key: id }),
      ) ||
      def.source.filename ||
      "<memory>";
    if (declaration.runtime) {
      if (!options.allowUnboundRuntime && !Object.hasOwn(runtime, id))
        throw new Error(
          `${sourceLocation}: asset ${JSON.stringify(id)} runtime binding is required`,
        );
      continue;
    }
    if (Object.hasOwn(runtime, id))
      throw new Error(`asset ${JSON.stringify(id)} has both static and runtime bindings`);
    const configured = declaration.path;
    if (!base && !isAbsolute(configured))
      throw new Error(
        `${sourceLocation}: asset ${JSON.stringify(id)} configured path ${JSON.stringify(configured)} requires an explicit filename or baseDir; no working-directory fallback`,
      );
    const path = isAbsolute(configured) ? configured : resolve(base!, configured);
    try {
      const info = await stat(path);
      if (!info.isFile()) throw new Error("not a regular file");
      if (info.size > MAX_IMAGE_BYTES) throw new Error("image exceeds 16 MiB");
      const bytes = await readFile(path);
      assets[id] = imageAsset(bytes);
    } catch (error) {
      throw new Error(
        `${sourceLocation}: asset ${JSON.stringify(id)} configured=${JSON.stringify(configured)} resolved=${JSON.stringify(path)} base=${JSON.stringify(base)}: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
  return nativeAssets(assets, Object.keys(def.assets));
}

export function bundleDirectory(outputPath: string): string {
  return `${outputPath.replace(/\.[^.\\/]+$/, "")}.assets`;
}

/** Build a deterministic manifest from already-read bytes so generation never rereads sources. */
export function assetManifest(assets: Assets): AssetManifest {
  const entries: AssetManifest["assets"] = Object.create(null);
  for (const [reference, asset] of Object.entries(assets)) {
    const id = reference.slice("<asset:".length, -1);
    const hash = createHash("sha256")
      .update(Buffer.from(asset.data_base64, "base64"))
      .digest("hex");
    entries[id] = { path: `${hash}.${asset.format === "png" ? "png" : "jpg"}`, sha256: hash };
  }
  return { version: 1, assets: entries };
}

export async function writeAssetBundle(
  directory: string,
  assets: Assets,
  manifest: AssetManifest,
  check = false,
): Promise<void> {
  const files = new Map<string, Uint8Array>();
  for (const [id, entry] of Object.entries(manifest.assets))
    files.set(entry.path, Buffer.from(assets[`<asset:${id}>`]!.data_base64, "base64"));
  files.set("manifest.json", Buffer.from(`${canonicalJson(manifest)}\n`));
  if (!check) await mkdir(directory, { recursive: true });
  for (const [name, bytes] of files) {
    const path = join(directory, name);
    if (check) {
      let existing: Buffer;
      try {
        existing = await readFile(path);
      } catch {
        throw new Error(`missing generated asset: ${path}`);
      }
      if (!existing.equals(Buffer.from(bytes))) throw new Error(`stale generated asset: ${path}`);
    } else {
      const temporary = `${path}.${randomUUID()}.tmp`;
      try {
        await writeFile(temporary, bytes);
        await rename(temporary, path);
      } finally {
        await rm(temporary, { force: true });
      }
    }
  }
}

/** Runtime helper for generated modules; anchor to the generated module, never the process cwd. */
export async function loadPackagedAssets(
  moduleURL: string,
  companion: string,
  manifest: AssetManifest,
  options: AssetLoadOptions = {},
  runtimeIds: readonly string[] = [],
): Promise<Assets> {
  const directory =
    options.baseDir !== undefined
      ? resolve(options.baseDir)
      : join(dirname(fileURLToPath(moduleURL)), companion);
  const assets: Assets = Object.assign(Object.create(null), options.runtimeAssets ?? {});
  validateAssets(assets);
  for (const id of runtimeIds)
    if (!Object.hasOwn(assets, id))
      throw new Error(`asset ${JSON.stringify(id)} runtime binding is required`);
  for (const [id, entry] of Object.entries(manifest.assets)) {
    if (Object.hasOwn(assets, id))
      throw new Error(`asset ${JSON.stringify(id)} has both static and runtime bindings`);
    if (basename(entry.path) !== entry.path || !/^[a-f0-9]{64}\.(png|jpg)$/.test(entry.path))
      throw new Error("invalid packaged asset path");
    const path = join(directory, entry.path);
    const bytes = await readFile(path);
    if (createHash("sha256").update(bytes).digest("hex") !== entry.sha256)
      throw new Error(`asset ${JSON.stringify(id)} hash mismatch: ${path}`);
    assets[id] = imageAsset(bytes);
  }
  return nativeAssets(assets, [...Object.keys(manifest.assets), ...runtimeIds]);
}

export function definitionAssetReferences(def: Definition): Set<string> {
  return assetReferences(def.questions);
}
