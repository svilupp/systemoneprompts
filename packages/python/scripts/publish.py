#!/usr/bin/env python3
"""Build and publish both Python distributions for the current version."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    name = project["name"]
    version = project["version"]
    run_quiet = ROOT / "scripts" / "run-quiet.sh"
    subprocess.run(
        ["sh", str(run_quiet), "Build", "--", "uv", "build", "--clear"],
        cwd=ROOT,
        check=True,
    )
    dist = ROOT / "dist"
    artifacts = [
        dist / f"{name}-{version}-py3-none-any.whl",
        dist / f"{name}-{version}.tar.gz",
    ]
    missing = [str(path) for path in artifacts if not path.is_file()]
    if missing:
        raise SystemExit(f"build did not produce: {', '.join(missing)}")
    subprocess.run(["uv", "publish", *(str(path) for path in artifacts)], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
