#!/usr/bin/env python3
"""Copy this package out of the repository and run locked checks there."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns(
    ".venv",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "*.pyc",
    ".DS_Store",
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="systemoneprompts-python-standalone-") as temp:
        destination = Path(temp) / "systemoneprompts-python"
        shutil.copytree(ROOT, destination, ignore=IGNORE)
        subprocess.run(["uv", "sync", "--locked", "--dev"], cwd=destination, check=True)
        subprocess.run(
            [
                "sh",
                str(destination / "scripts" / "run-quiet.sh"),
                "Checks",
                "--",
                "uv",
                "run",
                "--locked",
                "python",
                "scripts/check.py",
            ],
            cwd=destination,
            check=True,
        )
        subprocess.run(
            [
                "sh",
                str(destination / "scripts" / "run-quiet.sh"),
                "Package smoke",
                "--",
                "uv",
                "run",
                "--locked",
                "python",
                "scripts/package-smoke.py",
            ],
            cwd=destination,
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
