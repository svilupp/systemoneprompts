# Native TypeSafe images

Set `TYPESAFE_API_KEY`, then run from the package directory:

```sh
systemoneprompts check examples/13-native-images/rectangle.toml
systemoneprompts run examples/13-native-images/rectangle.toml --state examples/13-native-images/state.json --assets examples/13-native-images/assets.json --experimental-images --cache --json
systemoneprompts generate examples/13-native-images/rectangle.toml
```

The TOML bundles a static JPEG reference and declares a runtime `photo` slot.
`assets.json` supplies a PNG in the native JSON/base64 format. `state.json`
references it as `<asset:photo>`. Presence gates use of the Box answer; Box
always returns edges, including when a target is absent.

These synthetic 320 × 320 images exercise the integration. They do not establish
model quality. Use representative held-out photographs to tune thresholds.
Images need the explicit experimental flag; Box needs `jev-1.14.0` or
`jev-preview`. `jev-latest` still selects 1.13 as of 2026-10-16.

Deploy the generated module and its companion `.assets` directory together.
Load assets explicitly with generated `loadAssets` (TypeScript) or `load_assets`
(Python), supplying runtime bindings. Importing the module performs no image I/O.

The full repository guide is [docs/vision.md](../../../../docs/vision.md).
