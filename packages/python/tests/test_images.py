from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import io
import json
import shutil
from pathlib import Path
from typing import Any

import httpx2
import pytest
from PIL import Image

from systemoneprompts import (
    BoxAnswer,
    check_definition,
    create_factor_evaluator,
    generate,
    is_answer_shape,
    is_known_native_answer,
    load_definition,
    load_definition_assets,
    parse_definition,
    render_definition,
)
from systemoneprompts.assets import image_format, validate_assets
from systemoneprompts.cache import FetchResponse, create_caching_fetch, image_request_hash
from systemoneprompts.client import TypeSafeClient
from systemoneprompts.diagnostics import SystemOnePromptsError
from systemoneprompts.evaluation import load_eval_cases
from systemoneprompts.json_values import canonical_json

BOX = {"type": "box", "box": {"top": 0.1, "bottom": 0.8, "left": 0.2, "right": 0.9}, "confidence": 0.8}
QUESTIONS = {"target": {"type": "box", "instructions": "Find the object"}}
HEADER = {"TypeSafe-Danger-Zone-Images": "true"}


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (300, 300)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, "red").save(output, format=fmt)
    return output.getvalue()


def wire(data: bytes | None = None) -> dict[str, Any]:
    return {"photo": {"type": "image", "format": "png", "data_base64": base64.b64encode(data or image_bytes()).decode()}}


def test_box_typing_and_validation() -> None:
    assert BoxAnswer.model_validate(BOX).model_dump() == BOX
    assert is_answer_shape(BOX)
    assert not is_answer_shape({"type": "box", "box": None, "confidence": None})
    assert is_answer_shape({**BOX, "confidence": None})
    assert not is_known_native_answer({**BOX, "box": None})
    for bad in [True, -0.1, 1.1, float("inf")]:
        answer = {**BOX, "box": {**BOX["box"], "top": bad}}
        assert not is_answer_shape(answer)
        assert not is_known_native_answer(answer)
        with pytest.raises(ValueError):
            BoxAnswer.model_validate(answer)
    assert not is_answer_shape({**BOX, "box": {**BOX["box"], "left": 0.95}})
    assert not is_answer_shape({**BOX, "confidence": True})


def test_box_factors_and_parse() -> None:
    definition = parse_definition('[questions.target]\ntype="box"\n[factors.found]\nref="target"\nknown=true\nconfidence={gte=0.7}')
    assert not check_definition(definition)
    evaluate = create_factor_evaluator(definition.factor_definitions)
    assert evaluate({"target": BOX}) == {"found": True}
    assert evaluate({"target": {**BOX, "confidence": None}}) == {"found": False}
    with pytest.raises(SystemOnePromptsError, match="confidence"):
        create_factor_evaluator({"f": {"ref": "target", "confidence": {"gte": 0.5}}})({"target": {**BOX, "confidence": None}})
    for factor in ['all=["target"]', 'ref="target"\nscore={gte=1}', 'ref="target"\nchoice="red"']:
        invalid = parse_definition('[questions.target]\ntype="box"\n[factors.f]\n' + factor)
        assert any(item.severity == "error" for item in check_definition(invalid))
    assert any(d.code == "box-criteria" for d in parse_definition('[questions.target]\ntype="box"\ncriteria=[]').diagnostics)
    generated = render_definition(definition)
    assert 'type: Literal["box"]' in generated
    assert 'confidence: float | None' in generated


def test_asset_ref_declarations() -> None:
    source = '[questions.q]\ntype="box"\ninstructions="Find <asset:photo>"'
    assert any(d.code == "asset-unknown-ref" for d in check_definition(parse_definition(source)))
    definition = parse_definition(source + '\n[assets.photo]\nruntime=true')
    assert not check_definition(definition)
    with pytest.raises(SystemOnePromptsError, match="missing runtime"):
        load_definition_assets(definition)
    assert load_definition_assets(definition, wire()) == {"<asset:photo>": wire()["photo"]}
    assert any(d.code == "asset-declaration" for d in parse_definition(source + '\n[assets.photo]\nruntime=true\npath="x"').diagnostics)


@pytest.mark.parametrize("bad", [[], {"photo": {}}, {"photo": {"type": "image", "format": "gif", "data_base64": "AAAA"}}, {"photo": {"type": "image", "format": "png", "data_base64": "@@@@"}}])
def test_runtime_assets_invalid(bad: Any) -> None:
    with pytest.raises(SystemOnePromptsError):
        validate_assets(bad)


def test_actual_decoding() -> None:
    assert image_format(image_bytes()) == "png"
    assert image_format(image_bytes("JPEG")) == "jpg"
    for data in [image_bytes()[:-15], b"not an image", image_bytes(size=(100, 300)), b"x" * (16 * 1024 * 1024 + 1)]:
        with pytest.raises(SystemOnePromptsError):
            image_format(data)
    output = io.BytesIO()
    Image.new("RGB", (300, 300), "red").save(output, format="PNG", save_all=True, append_images=[Image.new("RGB", (300, 300), "blue")])
    with pytest.raises(SystemOnePromptsError, match="animated"):
        image_format(output.getvalue())


def definition_file(tmp_path: Path) -> Path:
    source = tmp_path / "source ü with spaces"
    source.mkdir()
    (source / "photo.png").write_bytes(image_bytes())
    file = source / "input.toml"
    file.write_text('[assets.photo]\npath="./photo.png"\n[questions.q]\ntype="box"\ninstructions="Find <asset:photo>"')
    return file


def test_static_cwd_independent_relocation_and_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = definition_file(tmp_path)
    definition = load_definition(str(file))
    monkeypatch.chdir(tmp_path)
    assert load_definition_assets(definition) == {"<asset:photo>": wire()["photo"]}
    with pytest.raises(SystemOnePromptsError, match="requires prepared_assets"):
        render_definition(definition)
    in_memory = parse_definition(definition.source or "")
    with pytest.raises(SystemOnePromptsError, match="explicit source"):
        load_definition_assets(in_memory)
    target = tmp_path / "out" / "custom.py"
    generate(definition, target)
    assert "source ü with spaces" not in target.read_text()
    manifest = json.loads((target.parent / "custom.assets" / "manifest.json").read_text())
    entry = manifest["assets"]["photo"]
    assert entry["sha256"] == hashlib.sha256(image_bytes()).hexdigest()
    assert entry["path"] == entry["sha256"] + ".png"
    relocated = tmp_path / "relocated"
    shutil.move(str(target.parent), relocated)
    shutil.rmtree(file.parent)
    monkeypatch.chdir(relocated)
    spec = importlib.util.spec_from_file_location("vision_generated", relocated / "custom.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.load_assets() == {"<asset:photo>": wire()["photo"]}
    (relocated / "custom.assets" / entry["path"]).write_bytes(b"bad")
    with pytest.raises(SystemOnePromptsError, match="hash mismatch"):
        module.load_assets()


@pytest.mark.parametrize("kind", ["missing", "directory", "broken", "corrupt"])
def test_static_errors_positioned(tmp_path: Path, kind: str) -> None:
    file = definition_file(tmp_path)
    image = file.parent / "photo.png"
    image.unlink()
    if kind == "directory":
        image.mkdir()
    elif kind == "broken":
        image.symlink_to(file.parent / "absent")
    elif kind == "corrupt":
        image.write_bytes(b"bad")
    with pytest.raises(SystemOnePromptsError, match="configured.*resolved.*base") as caught:
        load_definition_assets(load_definition(str(file)))
    assert caught.value.diagnostics[0].location.line is not None


def test_native_optin_assets_box_and_snapshot() -> None:
    calls: list[Any] = []
    request_assets = wire()
    questions = {"target": {"type": "box", "instructions": "Find <asset:photo>"}}
    class Http:
        def request(self, *args: Any, **kwargs: Any) -> Any:
            calls.append(kwargs)
            request_assets["photo"]["data_base64"] = "AAAA"
            questions["target"]["instructions"] = "mutated"
            if len(calls) == 1:
                return httpx2.Response(429, headers={"retry-after": "0"}, json={})
            return httpx2.Response(200, json={"model": "jev-1.14.0", "answers": {"target": BOX}, "usage": {"input_tokens": 1, "output_tokens": 1}})
    client = TypeSafeClient(http_client=Http(), environ={})
    with pytest.raises(SystemOnePromptsError, match="opt-in|TypeSafe-Danger"):
        client.system_one_sync(state={}, questions=QUESTIONS)
    response = client.system_one_sync(state={}, questions=questions, assets=request_assets, headers=HEADER)
    assert response["answers"]["target"] == BOX
    assert calls[0]["json"] == calls[1]["json"]
    assert calls[1]["json"]["questions"]["target"]["instructions"] == "Find <asset:photo>"
    assert calls[1]["json"]["assets"] == wire()


def test_native_async_and_malformed_box() -> None:
    class Http:
        async def request(self, *args: Any, **kwargs: Any) -> Any:
            return httpx2.Response(200, json={"model": "jev", "answers": {"target": {**BOX, "box": {**BOX["box"], "top": True}}}})
    client = TypeSafeClient(http_client=Http(), environ={})
    with pytest.raises(SystemOnePromptsError, match="invalid System One response"):
        asyncio.run(client.system_one(state={}, questions=QUESTIONS, headers=HEADER))


def test_image_cache_whole_request(tmp_path: Path) -> None:
    calls: list[Any] = []
    malformed = False
    def fetch(url: str, init: Any) -> FetchResponse:
        calls.append(json.loads(init["body"]))
        result = {"model": "jev", "answers": {"target": BOX if not malformed else {**BOX, "confidence": True}}, "usage": {"input_tokens": 2, "output_tokens": 1}}
        return FetchResponse(status=200, body=json.dumps(result).encode())
    caching = create_caching_fetch(dir=str(tmp_path), fetch=fetch)
    url = "https://api.typesafe.ai/v1/systemone"
    request = {"model": "jev-1.14.0", "state": {"b": 2, "a": 1, "photo": "<asset:photo>"}, "questions": QUESTIONS, "assets": wire()}
    def call(value: Any) -> Any:
        return caching(url, {"method": "POST", "headers": HEADER, "body": json.dumps(value)}).json()
    assert call(request)["usage"]["input_tokens"] == 2
    assert call({**request, "state": {"a": 1, "b": 2, "photo": "<asset:photo>"}})["usage"]["input_tokens"] == 0
    assert len(calls) == 1
    digest = image_request_hash(url, request)
    record = tmp_path / "images" / "v1" / digest[:2] / (digest + ".json")
    assert record.read_text() == canonical_json({"version": 1, "key": digest, "model": "jev", "requestedModel": "jev-1.14.0", "answers": {"target": BOX}, "usage": {"input_tokens": 2, "output_tokens": 1}}) + "\n"
    changed = {**request, "assets": wire(image_bytes(size=(301, 300)))}
    call(changed)
    assert len(calls) == 2
    assert all(set(item["questions"]) == {"target"} for item in calls)
    malformed = True
    bad = {**request, "state": {"changed": True, "photo": "<asset:photo>"}}
    call(bad)
    call(bad)
    assert len(calls) == 4


def test_eval_box_scalar_label_rejected() -> None:
    definition = parse_definition('[questions.target]\ntype="box"')
    with pytest.raises(SystemOnePromptsError, match="invalid eval"):
        load_eval_cases('{"state":{},"labels":{"target":1}}', "cases.jsonl", definition)


def test_providers_and_cached_adapters_reject_before_network(tmp_path: Path) -> None:
    from systemoneprompts.cloudflare_decisions import CloudflareDecisionsClient
    from systemoneprompts.cloudflare_dev import create_cached_cloudflare_decisions_client
    from systemoneprompts.dev import create_cached_openai_decisions_client
    from systemoneprompts.openai_decisions import OpenAIDecisionsClient
    calls: list[Any] = []
    def handle(request: Any) -> Any:
        calls.append(request)
        raise AssertionError("network must not be called")
    transport = httpx2.MockTransport(handle)
    openai = OpenAIDecisionsClient(transport=transport)
    cloudflare = CloudflareDecisionsClient(account_id="account", transport=transport)
    cached_openai = create_cached_openai_decisions_client(client=openai, dir=str(tmp_path / "openai"))["client"]
    cached_cloudflare = create_cached_cloudflare_decisions_client(client=cloudflare, dir=str(tmp_path / "cloudflare"))["client"]
    router = TypeSafeClient(provider="openrouter", transport=transport, environ={})
    legacy = TypeSafeClient(cloudflare_account_id="account", transport=transport, environ={})
    try:
        for client in [openai, cloudflare, cached_openai, cached_cloudflare, router, legacy]:
            with pytest.raises(SystemOnePromptsError, match="native TypeSafe"):
                asyncio.run(client.system_one(state={}, questions=QUESTIONS, headers=HEADER))
            with pytest.raises(SystemOnePromptsError, match="native TypeSafe"):
                asyncio.run(client.system_one(state="<asset:photo>", questions={"n": {"type": "noul", "instructions": "what?"}}, assets=wire(), headers=HEADER))
        assert not calls
        assert not list(tmp_path.rglob("*.json"))
    finally:
        for client in [openai, cloudflare, cached_openai, cached_cloudflare, router, legacy]:
            client.close()


def test_cli_freshness_image_only_and_missing_bundle(tmp_path: Path) -> None:
    from systemoneprompts.cli import main
    file = definition_file(tmp_path)
    output = tmp_path / "generated.py"
    assert main(["generate", str(file), "--out", str(output)]) == 0
    assert main(["generate", str(file), "--out", str(output), "--check"]) == 0
    (file.parent / "photo.png").write_bytes(image_bytes(size=(301, 300)))
    assert main(["generate", str(file), "--out", str(output), "--check"]) == 1
    assert main(["generate", str(file), "--out", str(output)]) == 0
    shutil.rmtree(output.parent / "generated.assets")
    assert main(["generate", str(file), "--out", str(output), "--check"]) == 1
    (file.parent / "photo.png").unlink()
    assert main(["check", str(file)]) == 1


def test_static_parent_path_and_symlink(tmp_path: Path) -> None:
    (tmp_path / "real.png").write_bytes(image_bytes())
    (tmp_path / "link.png").symlink_to(tmp_path / "real.png")
    folder = tmp_path / "nested"
    folder.mkdir()
    file = folder / "input.toml"
    file.write_text('[assets.photo]\npath="../link.png"\n[questions.q]\ntype="box"\ninstructions="<asset:photo>"')
    assert load_definition_assets(load_definition(str(file))) == {"<asset:photo>": wire()["photo"]}


def test_generated_import_does_not_read_bundle(tmp_path: Path) -> None:
    file = definition_file(tmp_path)
    output = tmp_path / "generated.py"
    generate(load_definition(str(file)), output)
    shutil.rmtree(tmp_path / "generated.assets")
    spec = importlib.util.spec_from_file_location("missing_bundle_generated", output)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemOnePromptsError, match="cannot read bundled"):
        module.load_assets()


def test_eval_preflights_all_runtime_assets(tmp_path: Path) -> None:
    from systemoneprompts.evaluation import execute_eval
    definition = parse_definition('[assets.photo]\nruntime=true\n[questions.q]\ntype="box"\ninstructions="<asset:photo>"')
    calls: list[Any] = []
    class Client:
        async def system_one(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return {"answers": {"q": BOX}}
    with pytest.raises(SystemOnePromptsError, match="missing runtime"):
        asyncio.run(execute_eval(definition, [{"state": {}, "assets": wire()}, {"state": {}}], Client(), model="jev-1.14.0"))
    assert not calls


def test_image_cache_decodes_compressed_response_once(tmp_path: Path) -> None:
    import gzip

    from systemoneprompts.provider import create_client
    calls: list[Any] = []
    def handle(request: Any) -> Any:
        calls.append(request)
        result = {"model": "jev-1.14.0", "answers": {"target": BOX}, "usage": {"input_tokens": 2, "output_tokens": 1}}
        return httpx2.Response(200, headers={"content-encoding": "gzip"}, content=gzip.compress(json.dumps(result).encode()))
    definition = parse_definition('[questions.target]\ntype="box"')
    created = create_client(definition, cache=True, cache_root=str(tmp_path), env={}, transport=httpx2.MockTransport(handle))
    try:
        first = asyncio.run(created["client"].system_one(state={}, questions=QUESTIONS, headers=HEADER))
        second = asyncio.run(created["client"].system_one(state={}, questions=QUESTIONS, headers=HEADER))
        assert first["answers"] == second["answers"] == {"target": BOX}
        assert second["usage"] == {"input_tokens": 0, "output_tokens": 0}
        assert len(calls) == 1
    finally:
        created["client"].close()
