"""Replay the recorded learning result through the existing Python contract."""

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/python/src"))


def main() -> None:
    from openai_decisions import QUESTIONS
    from systemoneprompts.answers import partition_answers
    from systemoneprompts.factors import create_factor_evaluator

    report = json.loads((ROOT / "tools/learning/openai-decisions-results.json").read_text())
    result = next(c["normalized"] for c in report["cases"] if c["name"] == "translated_mixed")
    partition = partition_answers(QUESTIONS, result["answers"])
    assert not partition["missing"] and not partition["malformed"], partition
    factors = create_factor_evaluator(
        {
            "billing": {"ref": "__proto__", "choice": "billing"},
            "charge": {"ref": "charged.twice", "noul": {"gte": 0.5}},
            "severity_band": {"ref": "severity", "score": {"gte": 0.5, "lte": 1.5}},
        }
    )(result["answers"])
    assert all(factors.values()), factors
    print(
        "Python: recorded normalized answers pass partition_answers and all three factor predicates"
    )


if __name__ == "__main__":
    main()
