#!/usr/bin/env python3
"""Publish an explicitly named artifact; dry-run is the safe default."""

from __future__ import annotations

import argparse
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    if not artifact.is_file():
        parser.error(f"artifact not found: {artifact}")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    expected = {f"systemoneprompts-{version}-py3-none-any.whl", f"systemoneprompts-{version}.tar.gz"}
    if artifact.name not in expected:
        parser.error(f"artifact filename must be one of: {', '.join(sorted(expected))}")
    command = ["uv", "publish", str(artifact)]
    print("Would run:", " ".join(command))
    if args.execute:
        subprocess.run(command, check=True)
    else:
        print("Dry run only; pass --execute to publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
