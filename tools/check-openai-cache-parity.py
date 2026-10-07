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


def run(language: str, directory: Path, action: str) -> None:
    command = (["bun", "tests/openai-cache-worker.ts"] if language == "ts" else
               [str(PY / ".venv/bin/python"), "tests/openai_cache_worker.py"])
    result = subprocess.run([*command, str(directory), action], cwd=TS if language == "ts" else PY,
                            text=True, capture_output=True, check=True)
    value = json.loads(result.stdout)
    assert value["calls"] == (1 if action == "write" else 0), value
    assert value["stats"]["hits"] == (0 if action == "write" else 3), value


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="openai-cache-parity-") as temporary:
        ts, py = Path(temporary) / "ts", Path(temporary) / "py"
        run("ts", ts, "write")
        run("py", ts, "read")
        run("py", py, "write")
        run("ts", py, "read")
        ts_records = {str(p.relative_to(ts)): p.read_bytes() for p in ts.rglob("*.json")}
        py_records = {str(p.relative_to(py)): p.read_bytes() for p in py.rglob("*.json")}
        assert len(ts_records) == 3
        assert ts_records == py_records, "cross-language namespace, hash, or record bytes differ"
    print("OpenAI cache parity: both directions read successfully; namespaces and record bytes match")


if __name__ == "__main__":
    main()
