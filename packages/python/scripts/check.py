#!/usr/bin/env python3
"""Run independent package-quality legs and report every failure."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUIET = ROOT / "scripts" / "run-quiet.sh"


def example_tomls() -> list[str]:
    return sorted(str(path) for path in (ROOT / "examples").glob("*/*.toml"))


def legs() -> dict[str, list[str]]:
    tomls = example_tomls()
    if not tomls:
        raise SystemExit("no example TOML files found under examples/*/*.toml")
    return {
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
        "Generated examples": [
            "uv",
            "run",
            "--locked",
            "systemoneprompts",
            "generate",
            "--check",
            *tomls,
        ],
    }


def main(argv: list[str]) -> int:
    known = legs()
    requested = argv or list(known)
    unknown = [name for name in requested if name not in known]
    if unknown:
        print(
            f"unknown check leg(s): {', '.join(unknown)}; known: {', '.join(known)}", file=sys.stderr
        )
        return 2
    failed = False
    for label in requested:
        result = subprocess.run(
            ["sh", str(QUIET), label, "--", *known[label]], cwd=ROOT, check=False
        )
        failed = failed or result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
