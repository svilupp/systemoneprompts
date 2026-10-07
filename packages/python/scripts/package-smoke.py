#!/usr/bin/env python3
"""Build wheel and sdist artifacts and verify a clean consumer can use them."""

from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROVIDER_SMOKE = """
import asyncio
import httpx2
from systemoneprompts import OpenAIDecisionsClient, create_factor_evaluator
from systemoneprompts.client import TypeSafeClient
for cls in (TypeSafeClient, OpenAIDecisionsClient):
    def handle(request):
        openai = cls is OpenAIDecisionsClient
        assert request.url.path == ("/v1/decisions" if openai else "/v1/systemone")
        answers = ([{"name": "q0", "type": "predicate", "probability": 0.9}] if openai
                   else {"ok": {"type": "noul", "noul": 0.9}})
        return httpx2.Response(200, json={"model": "mock", "usage": {"input_tokens": 1, "output_tokens": 0}, "answers": answers})
    client = cls(api_key="consumer-test", transport=httpx2.MockTransport(handle))
    try:
        result = asyncio.run(client.system_one(state="ok", questions={"ok": {"type": "noul", "instructions": "OK?"}}))
        assert create_factor_evaluator({"yes": {"ref": "ok", "noul": {"gte": 0.5}}})(result["answers"])["yes"]
    finally:
        client.close()
import tempfile
from systemoneprompts.dev import create_cached_openai_decisions_client
with tempfile.TemporaryDirectory() as directory:
    calls = []
    def cached_handle(request):
        calls.append(request)
        return httpx2.Response(200, json={"model": "mock", "usage": {"input_tokens": 1, "output_tokens": 0}, "answers": [{"name": "q0", "type": "predicate", "probability": 0.9}]})
    raw = OpenAIDecisionsClient(api_key="consumer-test", transport=httpx2.MockTransport(cached_handle))
    cached = create_cached_openai_decisions_client(client=raw, dir=directory)
    async def check():
        request = {"state": "ok", "questions": {"ok": {"type": "noul", "instructions": "OK?"}}}
        await cached["client"].system_one(**request)
        hit = await cached["client"].system_one(**request)
        assert hit["usage"] == {"input_tokens": 0, "output_tokens": 0}
        assert len(calls) == 1
    try:
        asyncio.run(check())
    finally:
        cached["client"].close()
        raw.close()

"""



def _assert_archive_contents(wheel: Path, source_dist: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert any(name.endswith("systemoneprompts/py.typed") for name in names), names
        assert any(name.endswith("licenses/LICENSE") or name.endswith("LICENSE") for name in names), names
        metadata = archive.read(next(name for name in names if name.endswith("METADATA"))).decode("utf-8")
        assert "Name: systemoneprompts" in metadata
        assert "Requires-Python: >=3.11" in metadata
    with tarfile.open(source_dist, "r:gz") as archive:
        members = archive.getnames()
        assert any(name.endswith("pyproject.toml") for name in members), members
        assert any(name.endswith("LICENSE") for name in members), members


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="systemoneprompts-python-smoke-") as temp:
        workspace = Path(temp)
        output = workspace / "dist"
        subprocess.run(["uv", "build", "--out-dir", str(output)], cwd=ROOT, check=True)
        wheel = next(output.glob("*.whl"))
        source_dist = next(output.glob("*.tar.gz"))
        _assert_archive_contents(wheel, source_dist)
        definition = workspace / "definition.toml"
        definition.write_text(
            '[questions]\nurgent = { type = "noul" }\n\n[factors]\nready = { ref = "urgent", noul = { gte = 0.5 } }\n',
            encoding="utf-8",
        )
        state = workspace / "state.json"
        state.write_text("{}", encoding="utf-8")
        answers = workspace / "answers.json"
        answers.write_text('{"urgent": {"noul": 0.8}}', encoding="utf-8")
        for artifact, label in ((wheel, "wheel"), (source_dist, "sdist")):
            venv = workspace / f"venv-{label}"
            # Pin the consumer venv to the interpreter running this script so the CI
            # matrix exercises each Python version rather than `.python-version`.
            subprocess.run(
                ["uv", "venv", "--python", sys.executable, str(venv)],
                cwd=ROOT,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            python = venv / "bin" / "python"
            subprocess.run(
                ["uv", "pip", "install", "--python", str(python), str(artifact)], check=True
            )
            located = subprocess.run(
                [str(python), "-c", "import systemoneprompts, pathlib; print(pathlib.Path(systemoneprompts.__file__).resolve())"],
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
            )
            installed = Path(located.stdout.strip())
            if ROOT.resolve() in installed.parents:
                raise SystemExit(f"import resolved to checkout sources: {installed}")
            typed = installed.with_name("py.typed")
            if not typed.exists():
                raise SystemExit("installed package is missing py.typed")
            checks = [
                [str(python), "-c", PROVIDER_SMOKE],
                [str(python), "-c", "import systemoneprompts; print(systemoneprompts.__file__)"],
                [str(python), "-c", "from systemoneprompts.client import TypeSafeClient; print(TypeSafeClient.__name__)"],
                [str(python), "-m", "systemoneprompts", "check", str(definition)],
                [str(python), "-m", "systemoneprompts", "generate", str(definition)],
                [
                    str(python),
                    "-m",
                    "systemoneprompts",
                    "run",
                    str(definition),
                    "--state",
                    str(state),
                    "--answers",
                    str(answers),
                ],
            ]
            for command in checks:
                subprocess.run(command, cwd=workspace, check=True)
            generated = workspace / "definition_generated.py"
            subprocess.run(
                [str(python), "-c", f"import importlib.util; spec=importlib.util.spec_from_file_location('g', {str(generated)!r}); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m.evaluate_factors({{'urgent': {{'noul': 0.8}}}}))"],
                cwd=workspace,
                check=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
