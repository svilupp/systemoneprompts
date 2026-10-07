#!/usr/bin/env python3
"""Prove TypeScript and Python write identical records and read each other's cache."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "packages/typescript"
PY = ROOT / "packages/python"


def run(language: str, directory: Path, action: str, provider: str) -> None:
    command = (["bun", "tests/provider-cache-worker.ts"] if language == "ts" else
               [str(PY / ".venv/bin/python"), "tests/provider_cache_worker.py"])
    result = subprocess.run([*command, str(directory), action, provider], cwd=TS if language == "ts" else PY,
                            text=True, capture_output=True, check=True)
    value = json.loads(result.stdout)
    assert value["calls"] == (1 if action == "write" else 0), value
    assert value["stats"]["hits"] == (0 if action == "write" else 3), value


def main() -> None:
    for provider in ("openai", "cloudflare"):
        with tempfile.TemporaryDirectory(prefix=f"{provider}-cache-parity-") as temporary:
            ts, py = Path(temporary) / "ts", Path(temporary) / "py"
            run("ts", ts, "write", provider)
            run("py", ts, "read", provider)
            run("py", py, "write", provider)
            run("ts", py, "read", provider)
            ts_records = {str(p.relative_to(ts)): p.read_bytes() for p in ts.rglob("*.json")}
            py_records = {str(p.relative_to(py)): p.read_bytes() for p in py.rglob("*.json")}
            assert len(ts_records) == 3
            assert ts_records == py_records, "cross-language namespace, hash, or record bytes differ"
        print(f"{provider}: bidirectional reads, scopes, and record bytes match")


if __name__ == "__main__":
    main()
