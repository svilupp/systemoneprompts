import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("localization", Path(__file__).parents[1] / "evaluate-localization.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LocalizationTests(unittest.TestCase):
    def test_iou_geometry(self):
        a = {"top": 0, "bottom": 0.5, "left": 0, "right": 0.5}
        b = {"top": 0.25, "bottom": 0.75, "left": 0.25, "right": 0.75}
        self.assertEqual(MODULE.iou(a, a), 1)
        self.assertAlmostEqual(MODULE.iou(a, b), 1 / 7)
        self.assertEqual(MODULE.iou(a, {"top": 0.5, "bottom": 1, "left": 0.5, "right": 1}), 0)

    def test_presence_miss_scores_zero_iou(self):
        box = {"top": 0, "bottom": 0.5, "left": 0, "right": 0.5}
        labels = {"a": {"present": True, "box": box}}
        predictions = {"a": {"model": "jev-1.14.0", "answers": {"target_present": {"type": "noul", "noul": 0.1}, "target_box": {"type": "box", "box": box, "confidence": None}}}}
        metrics, _ = MODULE.evaluate(labels, predictions, threshold=0.5, presence_question="target_present", box_question="target_box")
        self.assertEqual(metrics["mean_iou"], 0)
        self.assertEqual(metrics["false_negatives"], 1)

    def test_rejects_nonfinite_or_reversed_edges(self):
        for box in ({"top": 0, "bottom": float("nan"), "left": 0, "right": 1}, {"top": 0, "bottom": 1, "left": 0.5, "right": 0.5}):
            with self.assertRaises(ValueError):
                MODULE.valid_box(box)


if __name__ == "__main__":
    unittest.main()
