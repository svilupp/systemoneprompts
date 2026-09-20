#!/usr/bin/env python3
"""Set the package version. Does not commit, tag, or publish."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# This first release uses final semver versions only.
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if not VERSION.match(args.version):
        parser.error("--version must be a final release version such as 0.1.0")
    path = ROOT / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(r'(?m)^version = "[^"]+"', f'version = "{args.version}"', text, count=1)
    if count != 1:
        raise SystemExit("could not update version in pyproject.toml")
    path.write_text(updated, encoding="utf-8")
    subprocess.run(["uv", "lock"], cwd=ROOT, check=True)
    print(f"Prepared systemoneprompts -> {args.version}")
    print("Update CHANGELOG.md, run scripts/release-check.py, review the diff, then run scripts/publish.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
