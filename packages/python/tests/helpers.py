from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(relative: str) -> str:
    return (FIXTURES / relative).read_text(encoding="utf-8")


def fixture_path(relative: str) -> Path:
    return FIXTURES / relative


def run_cli(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in (
        "TYPESAFE_API_KEY",
        "TYPESAFE_MODEL",
        "TYPESAFE_DEFAULT_MODEL",
        "TYPESAFE_BASE_URL",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
    ):
        merged.pop(key, None)
    merged["TYPESAFE_BASE_URL"] = ""
    merged["CLOUDFLARE_ACCOUNT_ID"] = ""
    merged["CLOUDFLARE_API_TOKEN"] = ""
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, "-m", "systemoneprompts", *args],
        cwd=cwd or ROOT,
        env=merged,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
