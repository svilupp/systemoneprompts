#!/usr/bin/env python3
"""Run independent package-quality legs and report every failure."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUIET = ROOT / "scripts" / "run-quiet.sh"
LEGS = {
    "Lint": ["uv", "run", "--locked", "ruff", "check", "."],
    "Tests": ["uv", "run", "--locked", "pytest"],
    "Types": ["uv", "run", "--locked", "mypy"],
    "Build": ["uv", "build"],
    "Conformance": [
        "uv",
        "run",
        "--locked",
        "python",
        "scripts/conformance.py",
    ],
}


def main(argv: list[str]) -> int:
    requested = argv or list(LEGS)
    unknown = [name for name in requested if name not in LEGS]
    if unknown:
        print(
            f"unknown check leg(s): {', '.join(unknown)}; known: {', '.join(LEGS)}", file=sys.stderr
        )
        return 2
    failed = False
    for label in requested:
        result = subprocess.run(
            ["sh", str(QUIET), label, "--", *LEGS[label]], cwd=ROOT, check=False
        )
        failed = failed or result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
