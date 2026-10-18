#!/usr/bin/env python3
"""Score saved native Noul+Box predictions against held-out JSONL labels, offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path


def valid_box(value: object) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != {"top", "bottom", "left", "right"}:
        raise ValueError("box must contain exactly top, bottom, left, right")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in value.values()):
        raise ValueError("box edges must be finite numbers in [0, 1]")
    if value["left"] >= value["right"] or value["top"] >= value["bottom"]:
        raise ValueError("box edges must be ordered")
    return value


def iou(predicted: object, expected: object) -> float:
    a, b = valid_box(predicted), valid_box(expected)
    intersection = max(0, min(a["right"], b["right"]) - max(a["left"], b["left"])) * max(0, min(a["bottom"], b["bottom"]) - max(a["top"], b["top"]))
    area_a = (a["right"] - a["left"]) * (a["bottom"] - a["top"])
    area_b = (b["right"] - b["left"]) * (b["bottom"] - b["top"])
    return intersection / (area_a + area_b - intersection)


def rows(path: Path) -> dict[str, dict]:
    result = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"] or value["id"] in result:
            raise ValueError(f"{path}:{number}: missing or duplicate string id")
        result[value["id"]] = value
    if not result:
        raise ValueError(f"{path}: no cases")
    return result


def evaluate(labels: dict[str, dict], predictions: dict[str, dict], *, threshold: float, presence_question: str, box_question: str) -> tuple[dict, list]:
    if labels.keys() != predictions.keys():
        raise ValueError("prediction IDs must exactly match label IDs")
    details, overlaps, models = [], [], set()
    correct = false_positive = false_negative = positives = negatives = 0
    for case_id, label in labels.items():
        if not isinstance(label.get("present"), bool):
            raise ValueError(f"{case_id}: present label must be Boolean")
        prediction = predictions[case_id]
        model = prediction.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"{case_id}: prediction requires reported model/version")
        models.add(model)
        answers = prediction.get("answers", {})
        if not isinstance(answers, dict):
            raise ValueError(f"{case_id}: answers must be an object")
        present = answers.get(presence_question, {})
        if not isinstance(present, dict):
            raise ValueError(f"{case_id}: invalid presence Noul")
        score = present.get("noul")
        if present.get("type") != "noul" or isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"{case_id}: invalid presence Noul")
        region = answers.get(box_question, {})
        if not isinstance(region, dict) or "confidence" not in region:
            raise ValueError(f"{case_id}: invalid Box answer/confidence")
        confidence = region.get("confidence")
        if region.get("type") != "box" or (confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1)):
            raise ValueError(f"{case_id}: invalid Box answer/confidence")
        valid_box(region.get("box"))
        detected = score >= threshold
        truth = label["present"]
        correct += detected == truth
        positives += truth
        negatives += not truth
        false_positive += detected and not truth
        false_negative += truth and not detected
        detail = {"id": case_id, "present": truth, "detected": detected, "presence_score": score, "box_confidence": confidence}
        if truth:
            valid_box(label.get("box"))
            # A presence miss cannot earn localization credit from a box the app ignores.
            overlap = iou(region["box"], label.get("box")) if detected else 0.0
            overlaps.append(overlap)
            detail["iou"] = overlap
        elif label.get("box") is not None:
            raise ValueError(f"{case_id}: absent targets must have no box label")
        details.append(detail)
    metrics = {"models": sorted(models), "cases": len(labels), "positive_cases": positives, "negative_cases": negatives, "presence_accuracy": correct / len(labels), "false_positives": false_positive, "false_negatives": false_negative, "mean_iou": sum(overlaps) / len(overlaps) if overlaps else None, "iou50_rate": sum(value >= 0.5 for value in overlaps) / len(overlaps) if overlaps else None}
    return metrics, details


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--presence-question", default="target_present")
    parser.add_argument("--box-question", default="target_box")
    parser.add_argument("--presence-threshold", type=float, default=0.5)
    parser.add_argument("--min-presence-accuracy", type=float, default=0.95)
    parser.add_argument("--min-mean-iou", type=float, default=0.75)
    parser.add_argument("--min-iou50-rate", type=float, default=0.9)
    parser.add_argument("--min-cases", type=int, default=20)
    args = parser.parse_args()
    for name in ("presence_threshold", "min_presence_accuracy", "min_mean_iou", "min_iou50_rate"):
        if not 0 <= getattr(args, name) <= 1:
            parser.error(f"--{name.replace('_', '-')} must be in [0, 1]")
    if args.min_cases < 2:
        parser.error("--min-cases must be at least 2")
    if args.report.resolve() in (args.cases.resolve(), args.predictions.resolve()):
        parser.error("report must not overwrite cases or predictions")
    try:
        labels, predictions = rows(args.cases), rows(args.predictions)
        metrics, details = evaluate(labels, predictions, threshold=args.presence_threshold, presence_question=args.presence_question, box_question=args.box_question)
        gates = {"min_cases": args.min_cases, "min_presence_accuracy": args.min_presence_accuracy, "min_mean_iou": args.min_mean_iou, "min_iou50_rate": args.min_iou50_rate, "require_positive_and_negative_cases": True, "require_single_reported_model": True}
        checks = {"sample_size": metrics["cases"] >= args.min_cases, "both_classes": metrics["positive_cases"] > 0 and metrics["negative_cases"] > 0, "single_model": len(metrics["models"]) == 1, "presence_accuracy": metrics["presence_accuracy"] >= args.min_presence_accuracy, "mean_iou": metrics["mean_iou"] is not None and metrics["mean_iou"] >= args.min_mean_iou, "iou50_rate": metrics["iou50_rate"] is not None and metrics["iou50_rate"] >= args.min_iou50_rate}
        inputs = {}
        for name, path in (("cases", args.cases), ("predictions", args.predictions)):
            inputs[name] = {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        image_hashes = {}
        for case_id, label in labels.items():
            image = label.get("image")
            if image is not None:
                image_path = args.cases.parent / image
                image_hashes[case_id] = hashlib.sha256(image_path.read_bytes()).hexdigest()
        report = {"version": 1, "date": datetime.now(timezone.utc).isoformat(), "inputs": inputs, "image_sha256": image_hashes, "presence_threshold": args.presence_threshold, "gates": gates, "checks": checks, "passed": all(checks.values()), "metrics": metrics, "cases": details, "note": "Gates must be chosen before evaluating held-out representative data. Synthetic fixtures verify scoring only."}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps({"passed": report["passed"], "metrics": metrics}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
