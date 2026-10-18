from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx2
import pytest

from helpers import run_cli
from systemoneprompts import check_definition, generate, load_definition_assets, parse_definition
from systemoneprompts.assets import validate_assets
from systemoneprompts.client import TypeSafeClient
from systemoneprompts.diagnostics import SystemOnePromptsError
from test_asset_preflight import image_bytes, wire


@pytest.mark.parametrize("other", ["photo_reference", "photo2"])
@pytest.mark.parametrize("source", ["static", "runtime"])
def test_managed_and_generated_loaders_emit_complete_tokens(tmp_path: Path, other: str, source: str) -> None:
    (tmp_path / "photo.png").write_bytes(image_bytes())
    declaration = 'path="photo.png"' if source == "static" else "runtime=true"
    definition = parse_definition(f'[assets.photo]\n{declaration}\n[assets.{other}]\nruntime=true\n[questions.q]\ntype="noul"\ninstructions="Compare photo prose with <asset:{other}>"', filename=str(tmp_path / "input.toml"))
    assert not [d for d in check_definition(definition) if d.severity == "error"]
    runtime = {other: wire(), **({"photo": wire()} if source == "runtime" else {})}
    direct = load_definition_assets(definition, runtime)
    output = tmp_path / "output.py"
    generate(definition, output)
    spec = importlib.util.spec_from_file_location("managed_generated", output)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert list(module.asset_manifest["assets"]) == (["photo"] if source == "static" else [])
    packaged = module.load_assets(runtime)
    sent: list[Any] = []

    class Http:
        def request(self, *args: Any, **kwargs: Any) -> Any:
            sent.append(kwargs["json"])
            return httpx2.Response(200, json={"model": "jev", "answers": {"q": {"type": "noul", "noul": 1}}, "usage": {"input_tokens": 1, "output_tokens": 1}})

    client = TypeSafeClient(http_client=Http(), environ={})
    state = {"photo": "<asset:photo>", "text": f"photo and {other} are ordinary prose"}
    for assets in (direct, packaged):
        client.system_one_sync(state=state, questions=definition.questions, assets=assets, headers={"TypeSafe-Danger-Zone-Images": "true"})
        assert set(sent[-1]["assets"]) == {"<asset:photo>", f"<asset:{other}>"}
        assert sent[-1]["state"] == state
        assert sent[-1]["questions"]["q"]["instructions"] == f"Compare photo prose with <asset:{other}>"
    assert packaged == direct
    for load in (lambda bindings: load_definition_assets(definition, bindings), module.load_assets):
        with pytest.raises(SystemOnePromptsError, match="collid"):
            load({**runtime, "<asset:photo>": wire()})


def test_managed_loaders_keep_raw_keys_and_reject_static_override(tmp_path: Path) -> None:
    definition = parse_definition('[assets.photo]\nruntime=true\n[questions.q]\ntype="noul"')
    assert load_definition_assets(definition, {"photo": wire(), "<extra>": wire()}) == {"<asset:photo>": wire(), "<extra>": wire()}
    (tmp_path / "photo.png").write_bytes(image_bytes())
    static = parse_definition('[assets.photo]\npath="photo.png"\n[questions.q]\ntype="noul"', filename=str(tmp_path / "input.toml"))
    with pytest.raises(SystemOnePromptsError, match="collision"):
        load_definition_assets(static, {"photo": wire()})
    with pytest.raises(SystemOnePromptsError, match="unused"):
        validate_assets(load_definition_assets(static), questions=static.questions, state={})


def test_cli_static_state_only_asset_check_generate_and_run(tmp_path: Path) -> None:
    received: list[Any] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"model": "jev", "answers": {"q": {"type": "noul", "noul": 1}}, "usage": {"input_tokens": 1, "output_tokens": 1}}).encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (tmp_path / "photo.png").write_bytes(image_bytes())
        source = tmp_path / "input.toml"
        source.write_text('[assets.photo]\npath="photo.png"\n[questions.q]\ntype="noul"\ninstructions="Does the photo show a rectangle?"')
        state = tmp_path / "state.json"
        state.write_text('{"image":"<asset:photo>"}')
        for command in (["check", str(source)], ["generate", str(source)], ["generate", "--check", str(source)]):
            result = run_cli(command)
            assert result.returncode == 0, result.stderr
        args = ["run", str(source), "--state", str(state), "--experimental-images", "--base-url", f"http://127.0.0.1:{server.server_port}", "--json"]
        valid = run_cli(args, env={"TYPESAFE_API_KEY": "test"})
        assert valid.returncode == 0, valid.stderr
        assert received[0]["assets"] == {"<asset:photo>": wire()}
        state.write_text("{}")
        unused = run_cli(args, env={"TYPESAFE_API_KEY": "test"})
        assert unused.returncode == 1
        assert "unused" in unused.stderr
        assert len(received) == 1
        (tmp_path / "photo.png").write_bytes(b"corrupt")
        for command in ("check", "generate"):
            assert run_cli([command, str(source)]).returncode == 1
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
