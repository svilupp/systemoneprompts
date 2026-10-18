# Native TypeSafe images and Box

Send image evidence and locate a target with Jev 1.14. This integration uses
JSON/base64 with native TypeSafe; it does not generate images.

## Quick start

Set `TYPESAFE_API_KEY`, then run either package's example:

```sh
systemoneprompts run examples/13-native-images/rectangle.toml --state examples/13-native-images/state.json --assets examples/13-native-images/assets.json --experimental-images --json
```

Pin `jev-1.14.0` for Box. As of 2026-10-16, `jev-preview` selects 1.14 and
`jev-latest` selects 1.13. Images work with both 1.13 and 1.14; Box needs 1.14.
TypeSafe marks this API experimental. `--experimental-images` sends
`TypeSafe-Danger-Zone-Images: true`. Programmatic clients require that header too.
OpenAI, OpenRouter, Cloudflare Decisions, and legacy Cloudflare/Jev reject
image assets and Box locally, including when a cache might contain an answer.

## Declare assets

```toml
model = "jev-1.14.0"

[assets.reference_mug]
path = "./images/reference-mug.jpg"

[assets.photo]
runtime = true

[requires]
photo = "string"

[questions.mug_present]
type = "noul"
instructions = "Does `photo` contain the mug shown in <asset:reference_mug>?"

[questions.mug_box]
type = "box"
instructions = "The mug in `photo` matching <asset:reference_mug>."

[factors]
present = { ref = "mug_present", noul = { gte = 0.5 } }
box_usable = { ref = "mug_box", known = true, confidence = { gte = 0.8 } }
can_crop = { all = ["present", "box_usable"] }
```

Managed asset IDs must be nonempty and contain no `<` or `>` characters.
Each declaration has exactly one source: a nonblank `path` or `runtime = true`. Paths resolve
from the TOML directory. Parsing remains pure; file loading and CLI preflight
validate images before requests. `check` and `generate` catch undeclared
`<asset:...>` references in question strings. References work inside nested
instructions and criteria; object keys remain literal. `[data]` stays
application-owned and is never forwarded automatically.

Supply runtime evidence as a binding map. For example, state is
`{"photo":"<asset:photo>"}` and `assets.json` contains:

```json
{"photo":{"type":"image","format":"jpg","data_base64":"<standard padded base64 of the JPEG file>"}}
```

`--assets` and eval case `assets` read this binding map. Declared runtime slots
use logical IDs (`photo`) as keys. Managed loaders combine static images and
runtime bindings, returning complete token keys (`<asset:photo>`) for the native
client `assets` argument. Declarations and bundle manifests retain logical IDs;
source strings stay unchanged. Undeclared binding keys remain raw native references.
A raw key that duplicates an emitted managed token is rejected.
Runtime bindings must satisfy declared slots without replacing static assets.
Static assets may be referenced only by state. Missing and unused asset references
fail on the final request before transport. References use the
reserved `<asset:id>` spelling throughout state, instructions, and criteria.
There is no new `[requires]` image type; state still contains JSON strings.

Low-level clients also accept native reference strings such as `<photo>` as
asset-map keys. Native references match string values in state, instructions,
and criteria; object keys never count as uses. Whole values match first, then
substrings match left to right without overlap. If two references start at the
same position inside a longer string, local validation rejects the ambiguity;
use distinct references. Each key must be nonblank, at most 1,024 UTF-8 bytes,
and all keys together at most 65,536 bytes. The library reserves `<asset:id>`
for managed references and checks that its binding exists even in low-level calls.

## Read the answer

```json
{"type":"box","box":{"top":0.25,"bottom":0.82,"left":0.44,"right":0.84},"confidence":0.92}
```

Edges are fractions measured from the top-left: `0 <= top < bottom <= 1` and
`0 <= left < right <= 1`. Multiply horizontal edges by image width and vertical
edges by height for pixel coordinates. Confidence is a number in `[0,1]` or
`null`; null is unknown. A guarded `known = true` confidence predicate returns
false for null; an unguarded numeric confidence comparison fails.

Box has no criteria and no absent-target answer. Ask a Noul presence question
alongside it and ignore the box when the target is absent. The thresholds above
are examples; choose them using held-out images from your application.

## Deploy generated modules

```sh
systemoneprompts generate decisions.toml
systemoneprompts generate decisions.toml --check
```

Generation writes content-addressed static files beside the module in
`decisions.generated.assets/` (TypeScript) or `decisions_generated.assets/`
(Python). Copy that entire directory next to the emitted module when deploying,
including when compiling TypeScript into `dist`. The original TOML and source
images are unnecessary at runtime. `generate --check` includes image contents
and the companion bundle in freshness checks.

Generated modules do no image I/O at import. Load and bind explicitly:

```typescript
const assets = await loadAssets({ runtimeAssets: photoAssets });
// Optional baseDir points at the companion directory after a custom relocation.
```

```python
assets = load_assets(photo_assets)
# Optional bundle_base points at the companion directory after a custom relocation.
```

The default location is anchored to `import.meta.url` or `__file__`, independent
of process working directory. Loaders verify bundled file hashes.

## Limits and caching

Prepare still PNG or JPEG files with both dimensions from 280 through 1568 pixels
and at most 16 MiB per decoded file. Static files and runtime base64 are fully
decoded before cache lookup or transport; the declared format must match the
bytes (`jpg` and `jpeg` are equivalent). Rotate pixels upright before saving; the API
does not apply EXIF orientation. The library never resizes or fetches image URLs.
The JSON body has a 32 MiB limit. TypeSafe also imposes 32 MiB aggregate processed
and expanded request limits; repeated references count repeatedly after expansion,
and server re-encoding can increase image size. Local byte checks cannot predict
that processed size exactly.

Image and Box calls use a whole-request cache under `images/v1` in the cache
root. Keys include endpoint, provider, model, state, every question, and image
bytes. Image changes and question changes invalidate the whole request. Text-only
requests retain the existing per-question cache. All-hit usage is zero. Cached
responses undergo the same native response validation as live responses.

Disk statistics count physical records: one per text question or whole image
request. Model counts and drift use those records too. In-memory hits and misses
count questions. New image records include `requestedModel` when available;
older records remain readable and counted, but cannot report drift when their
requested model is unknown.

## Validate transport and localization separately

The default provider matrix retains the 1.13 text regression. Opt into the
bounded vision lane in both languages:

```sh
python3 tools/run-live-providers.py --live --provider typesafe --variation vision --report /tmp/native-vision.json
```

It sends one 1.13 image/Noul request and one 1.14 image/Noul/Box request per
language, then replays each through the cache. Artificial rectangle fixtures
verify transport only.

Use `tools/evaluate-localization.py` for separate offline localization scoring.
Each label JSONL row has `id`, Boolean `present`, optional relative `image`, and
normalized `box` for present targets. Each prediction row has the same `id`,
reported `model`, and native `answers.target_present`/`answers.target_box`.

```sh
python3 tools/evaluate-localization.py --cases heldout/labels.jsonl --predictions predictions.jsonl --report /tmp/localization.json --min-cases 100 --min-presence-accuracy 0.95 --min-mean-iou 0.75 --min-iou50-rate 0.9
```

Choose gates before inference on held-out representative images, including absent
targets. Reports record the gates, model/version, file/image hashes, presence
accuracy, false positives/negatives, mean IoU, and fraction of present cases with
IoU at least 0.5. A presence miss receives zero IoU; boxes on absent images are
ignored. Mixed model versions and missing positive/negative classes fail gates.
Scalar Box labels in the ordinary `eval` command are rejected.

Sources checked 2026-10-16: [TypeSafe images](https://docs.typesafe.ai/images),
[Box](https://docs.typesafe.ai/primitives/box),
[models](https://docs.typesafe.ai/models).
