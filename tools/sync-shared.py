#!/usr/bin/env python3
"""Validate that checked-in shared corpus copies have not drifted."""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "conformance" / "v1"
TARGETS = (
    ROOT / "packages" / "typescript" / "conformance" / "v1",
    ROOT / "packages" / "python" / "conformance" / "v1",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = [path.relative_to(SOURCE) for path in SOURCE.rglob("*") if path.is_file()]
    drift = False
    for target in TARGETS:
        for relative in files:
            source = SOURCE / relative
            destination = target / relative
            if args.check:
                if not destination.exists() or digest(source) != digest(destination):
                    print(f"shared corpus drift: {destination}")
                    drift = True
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    return int(drift)


if __name__ == "__main__":
    raise SystemExit(main())
