#!/usr/bin/env python3
"""Run the deterministic package checks required before a release."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUIET = ROOT / "scripts" / "run-quiet.sh"


def run(label: str, script: str) -> int:
    result = subprocess.run(
        ["sh", str(QUIET), label, "--", sys.executable, script],
        cwd=ROOT,
        check=False,
    )
    return result.returncode


def main() -> int:
    for script in ("scripts/check.py", "scripts/package-smoke.py"):
        status = run("Checks" if script.endswith("check.py") else "Package smoke", script)
        if status != 0:
            return status
    print("Release check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
