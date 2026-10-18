from __future__ import annotations

import base64
import io
from typing import Any

import httpx2
import pytest
from PIL import Image

from systemoneprompts import check_definition, parse_definition
from systemoneprompts.assets import used_asset_references, validate_assets
from systemoneprompts.client import TypeSafeClient
from systemoneprompts.diagnostics import SystemOnePromptsError

HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}
QUESTIONS = {"q": {"type": "noul", "instructions": "<asset:photo>"}}


def image_bytes(fmt: str = "PNG", **options: Any) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (300, 300)).save(output, format=fmt, **options)
    return output.getvalue()


def wire(data: bytes | None = None, fmt: str = "png") -> dict[str, Any]:
    return {"type": "image", "format": fmt, "data_base64": base64.b64encode(image_bytes() if data is None else data).decode()}


def test_public_client_rejects_invalid_runtime_images_before_transport() -> None:
    calls: list[Any] = []
    class Http:
        def request(self, *args: Any, **kwargs: Any) -> Any:
            calls.append(kwargs)
            raise AssertionError("transport called")
    client = TypeSafeClient(http_client=Http(), environ={})
    png = image_bytes()
    animated = png[:33] + bytes.fromhex("000000086163544c000000010000000000000000") + png[33:]
    for invalid in [wire(b"not an image"), wire(fmt="jpg"), wire(png[:-12]), wire(animated), wire(image_bytes("JPEG")[:-2], "jpg")]:
        with pytest.raises(SystemOnePromptsError):
            client.system_one_sync(state={}, questions=QUESTIONS, assets={"photo": invalid}, headers=HEADERS)
    assert calls == []


def test_valid_formats_preserve_exact_runtime_wire_bytes() -> None:
    calls: list[Any] = []
    class Http:
        def request(self, *args: Any, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return httpx2.Response(200, json={"model": "jev", "answers": {"q": {"type": "noul", "noul": 1}}, "usage": {"input_tokens": 1, "output_tokens": 1}})
    client = TypeSafeClient(http_client=Http(), environ={})
    for asset in [wire(), wire(image_bytes("JPEG"), "jpg"), wire(image_bytes("JPEG"), "jpeg"), wire(image_bytes("JPEG", progressive=True), "jpeg")]:
        client.system_one_sync(state={}, questions=QUESTIONS, assets={"photo": asset}, headers=HEADERS)
        assert calls[-1]["json"]["assets"]["photo"] == asset


def test_native_reference_matching_and_limits() -> None:
    validate_assets({"<photo>": wire()}, state="<photo>")
    assert used_asset_references(["category", "cat"], ["cat", "category"]) == {"category", "cat"}
    assert used_asset_references("abcde", ["abc", "bcd"]) == {"abc"}
    with pytest.raises(SystemOnePromptsError, match="ambiguous"):
        used_asset_references("a category", ["cat", "category"])
    for assets, state, questions, message in [
        ({"abc": wire(), "bcd": wire()}, "abcde", {}, "unused"),
        ({"photo": wire()}, {}, {"photo": {"type": "noul"}}, "unused"),
        ({"<photo>": wire()}, "<asset:missing>", {}, "missing"),
        ({" ": wire()}, {}, {}, "reference"),
        ({"é" * 513: wire()}, {}, {}, "reference"),
    ]:
        with pytest.raises(SystemOnePromptsError, match=message):
            validate_assets(assets, state=state, questions=questions)
    # Binding helpers do not know the eventual state, so defer the unused check.
    assert validate_assets({"photo": wire()}) == {"photo": wire()}


@pytest.mark.parametrize("declaration", ['[assets.""]\nruntime=true', '[assets."<bad>"]\nruntime=true', '[assets.photo]\npath="   "', '[assets.photo]\npath="x"\nruntime=true', '[assets.photo]\nruntime=false', '[assets.photo]\npath=123'])
def test_invalid_managed_declarations(declaration: str) -> None:
    definition = parse_definition(declaration + '\n[questions.q]\ntype="noul"')
    assert any(d.code == "asset-declaration" for d in definition.diagnostics)


@pytest.mark.parametrize("field", ['instructions="<asset:missing>"', 'criteria={true={example="<asset:missing>"}}'])
def test_unknown_ref_diagnostic_actual_question_field(field: str) -> None:
    definition = parse_definition('[questions.first]\ntype="noul"\ninstructions="fine"\n[questions."second.part"]\ntype="noul"\n' + field)
    diagnostic = next(d for d in check_definition(definition) if d.code == "asset-unknown-ref")
    assert diagnostic.location.line == 6


def test_unknown_ref_diagnostic_nested_literal_question() -> None:
    definition = parse_definition('[questions.first]\ntype="noul"\n[questions."second.part"]\ntype="noul"\n[questions."second.part".instructions]\nphoto="<asset:missing>"')
    diagnostic = next(d for d in check_definition(definition) if d.code == "asset-unknown-ref")
    assert diagnostic.location.line == 5
