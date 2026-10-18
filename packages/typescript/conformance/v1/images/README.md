# Image transport fixtures

Deterministic 320 × 320 PNGs and a baseline JPEG exercise decoding, asset
binding, bundling, and transport. `rectangle` contains a red rectangle with
normalized edges `{top: 0.25, bottom: 0.75, left: 0.25, right: 0.75}`;
`empty` is white. Rebuild with `python3 tools/make-image-fixtures.py` (Pillow).

These artificial images test integration. They do not establish localization
quality on photographs or a production confidence threshold.

The JSONL labels and mock predictions exercise the offline scorer without
inference. Run `python3 tools/evaluate-localization.py --cases
conformance/v1/images/localization-labels.jsonl --predictions
conformance/v1/images/localization-mock-predictions.jsonl --min-cases 2 --report
/tmp/localization-scorer.json` from the repository root. Its perfect synthetic
score describes the fixture, not a model result.
