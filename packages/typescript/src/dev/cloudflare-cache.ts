import { createHash } from "node:crypto";
import { join } from "node:path";
import type { SystemOneCallOptions } from "../client.js";
import type { CloudflareDecisionsClient } from "../cloudflare-decisions.js";
import {
  CloudflareDecisionsError,
  encodeDecisionsRequest,
  incompatible,
  isValidDecisionsAnswer,
  modelName,
  normalizeDecisionsBaseURL,
  validateNormalizedDecisionsResult,
} from "../cloudflare-decisions-codec.js";
import type { Fetch, Questions, SystemOneRequest, SystemOneResult } from "../native.js";
import { type CacheMode, type CachingFetch, createCachingFetch } from "./cache.js";

const callOptions = Symbol("Decisions call options");
type CanonicalInit = RequestInit & { [callOptions]?: SystemOneCallOptions };

/** `dir` is a cache root; the provider, adapter version, and origin scope are appended. */
export function cloudflareCacheDir(
  options: { dir?: string; baseURL?: string; accountId?: string; cwd?: string } = {},
): string {
  if (!options.baseURL && !(options.accountId?.trim() || process.env.CLOUDFLARE_ACCOUNT_ID?.trim()))
    incompatible("missing-account", "CLOUDFLARE_ACCOUNT_ID is required to resolve the cache scope");
  const root = options.dir ?? join(options.cwd ?? process.cwd(), ".systemoneprompts");
  const origin = createHash("sha256")
    .update(
      normalizeDecisionsBaseURL(
        options.baseURL,
        options.accountId?.trim() || process.env.CLOUDFLARE_ACCOUNT_ID?.trim() || "",
      ),
    )
    .digest("hex");
  return join(root, "providers", "cloudflare-decisions", "v1", origin, "cache");
}

/** Cache the canonical System One envelope; only the inner adapter sees Decisions wire JSON. */
export function createCachedCloudflareDecisionsClient(options: {
  client: CloudflareDecisionsClient;
  dir?: string;
  mode?: CacheMode;
}): {
  client: {
    systemOne<const Q extends Questions>(
      request: SystemOneRequest<Q>,
      call?: SystemOneCallOptions,
    ): Promise<SystemOneResult<Q>>;
  };
  cache: CachingFetch;
} {
  if (options.mode !== undefined && !["read-write", "read-only", "refresh"].includes(options.mode))
    incompatible("cloudflare-cache-mode", "Unknown cache mode");
  const network = options.client;
  const adapter: Fetch = async (_url, init) => {
    const request = JSON.parse(String(init?.body)) as SystemOneRequest;
    const result = await network.systemOne(request, (init as CanonicalInit)?.[callOptions]);
    // Decoding completes before the cache sees a successful response or writes any record.
    return Response.json(result);
  };
  const cache = createCachingFetch({
    dir: cloudflareCacheDir({ dir: options.dir, baseURL: network.baseURL }),
    mode: options.mode,
    fetch: adapter,
    validateEntry: isValidDecisionsAnswer,
  });
  const client = {
    async systemOne<const Q extends Questions>(
      request: SystemOneRequest<Q>,
      call: SystemOneCallOptions = {},
    ): Promise<SystemOneResult<Q>> {
      if (call.timeout !== undefined && (!Number.isFinite(call.timeout) || call.timeout <= 0))
        incompatible("cloudflare-options", "timeout must be positive");
      const model = modelName(request.model === undefined ? network.defaultModel : request.model);
      encodeDecisionsRequest(request.state, request.questions, model);
      const snapshot = structuredClone({
        state: request.state,
        questions: request.questions,
        model,
      });
      const init: CanonicalInit = {
        method: "POST",
        body: JSON.stringify(snapshot),
        [callOptions]: call,
      };
      if (call.signal?.aborted)
        throw new CloudflareDecisionsError("Decisions request aborted", { kind: "transport" });
      const response = await cache("https://systemoneprompts.invalid/v1/systemone", init);
      if (call.signal?.aborted)
        throw new CloudflareDecisionsError("Decisions request aborted", { kind: "transport" });
      return validateNormalizedDecisionsResult(await response.json(), snapshot.questions);
    },
  };
  return { client, cache };
}
