"""Image validation, definition bindings, and relocatable generated asset bundles."""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .diagnostics import SystemOnePromptsError, diagnostic

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 32 * 1024 * 1024
ASSET_REFERENCE = re.compile(r"<asset:([^<>]+)>")


def _error(message: str, code: str = "image-assets") -> Any:
    raise SystemOnePromptsError(diagnostic("error", code, message))


def asset_references(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(ASSET_REFERENCE.findall(value))
    if isinstance(value, Mapping):
        return set().union(*(asset_references(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(asset_references(item) for item in value)) if value else set()
    return set()


def validate_assets(assets: Any, *, questions: Any = None, state: Any = None) -> dict[str, Any]:
    if assets is None:
        result: dict[str, Any] = {}
    elif type(assets) is not dict:
        _error("assets must be an image reference map")
    else:
        result = {}
        total = 0
        reference_bytes = 0
        for ref, value in assets.items():
            if not isinstance(ref, str) or not ref.strip() or len(ref.encode("utf-8")) > 1024:
                _error(f"invalid asset reference {ref!r}: must be nonblank and at most 1024 UTF-8 bytes")
            reference_bytes += len(ref.encode("utf-8"))
            if reference_bytes > 65536:
                _error("asset references exceed 65536 UTF-8 bytes")
            if type(value) is not dict or set(value) != {"type", "format", "data_base64"}:
                _error(f"asset {ref!r} must contain only type, format, and data_base64")
            if value["type"] != "image" or value["format"] not in ("png", "jpg", "jpeg") or not isinstance(value["data_base64"], str):
                _error(f"asset {ref!r} must be a PNG or JPEG image")
            if len(value["data_base64"]) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
                _error(f"asset {ref!r} exceeds 16 MiB")
            try:
                data = base64.b64decode(value["data_base64"], validate=True)
            except (ValueError, binascii.Error):
                _error(f"asset {ref!r} has invalid base64")
            if base64.b64encode(data).decode("ascii") != value["data_base64"]:
                _error(f"asset {ref!r} has noncanonical base64")
            if not data or len(data) > MAX_IMAGE_BYTES:
                _error(f"asset {ref!r} must contain 1..{MAX_IMAGE_BYTES} decoded bytes")
            actual = image_format(data)
            if actual != ("jpg" if value["format"] == "jpeg" else value["format"]):
                _error(f"asset {ref!r} bytes do not match declared format {value['format']!r}")
            total += len(data)
            result[ref] = dict(value)
        if total > MAX_TOTAL_IMAGE_BYTES:
            _error("assets exceed 32 MiB decoded total")
    if questions is not None or state is not None:
        values = [state, *[value for question in (questions or {}).values() for key, value in question.items() if key in ("instructions", "criteria")]]
        missing = {ref for ref in asset_references(values) if ref not in result and f"<asset:{ref}>" not in result}
        if missing:
            _error("missing image asset bindings: " + ", ".join(sorted(missing)))
        unused = set(result) - used_asset_references(values, list(result))
        if unused:
            _error("unused image assets: " + ", ".join(sorted(unused)))
    return result


def used_asset_references(value: Any, references: list[str]) -> set[str]:
    """Match whole values first, then left-to-right nonoverlapping native references."""
    if isinstance(value, str):
        if value in references:
            return {value}
        used: set[str] = set()
        cursor = 0
        while cursor < len(value):
            positions = [(value.find(ref, cursor), ref) for ref in references]
            positions = [(position, ref) for position, ref in positions if position >= 0]
            if not positions:
                break
            first = min(position for position, _ in positions)
            matches = [ref for position, ref in positions if position == first]
            if len(matches) > 1:
                _error(f"ambiguous overlapping asset references at {value[first:]!r}; use distinct references")
            ref = matches[0]
            used.add(ref)
            cursor = first + len(ref)
        return used
    if isinstance(value, Mapping):
        return set().union(*(used_asset_references(item, references) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(used_asset_references(item, references) for item in value)) if value else set()
    return set()


def image_format(data: bytes) -> str:
    if not data or len(data) > MAX_IMAGE_BYTES:
        _error("image must contain 1..16 MiB")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        offset = 8
        ended = False
        while offset < len(data):
            if offset + 12 > len(data):
                _error("truncated PNG image")
            length = int.from_bytes(data[offset:offset + 4], "big")
            kind = data[offset + 4:offset + 8]
            offset += length + 12
            if offset > len(data):
                _error("truncated PNG image")
            if kind == b"acTL":
                _error("animated PNG images are unsupported")
            if kind == b"IEND":
                if length or offset != len(data):
                    _error("invalid PNG end")
                ended = True
        if not ended:
            _error("truncated PNG image")
    elif data.startswith(b"\xff\xd8") and not data.endswith(b"\xff\xd9"):
        _error("truncated JPEG image")
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
            if fmt not in ("PNG", "JPEG"):
                _error("image bytes must be PNG or JPEG")
            if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1:
                _error("animated PNG images are unsupported")
            if not all(280 <= size <= 1568 for size in image.size):
                _error("image dimensions must each be between 280 and 1568 pixels")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except SystemOnePromptsError:
        raise
    except Exception as error:
        _error(f"corrupt or unsupported image bytes: {error}")
    return "png" if fmt == "PNG" else "jpg"


def prepare_assets(definition: Any, *, base_dir: str | Path | None = None) -> dict[str, Any]:
    declarations = definition.assets
    files: dict[str, bytes] = {}
    manifest: dict[str, Any] = {"version": 1, "assets": {}}
    base = Path(base_dir) if base_dir is not None else Path(definition.source_path).parent if definition.source_path else None
    for ref, declaration in declarations.items():
        if declaration.get("runtime") is True:
            continue
        configured = declaration["path"]
        if base is None:
            _error(f"asset {ref!r} path {configured!r} requires an explicit source filename or base_dir", "asset-source-base")
        assert base is not None
        resolved = Path(os.path.abspath(base / configured))
        try:
            if not resolved.is_file():
                raise OSError("not a regular file")
            if resolved.stat().st_size > MAX_IMAGE_BYTES:
                raise OSError("image exceeds 16 MiB")
            data = resolved.read_bytes()
            fmt = image_format(data)
        except (OSError, SystemOnePromptsError) as error:
            location = __import__("systemoneprompts.locate", fromlist=["locate"]).locate(definition.source_index, table=["assets", ref], section="assets", key=ref)
            raise SystemOnePromptsError(diagnostic("error", "asset-file", f"asset {ref!r}: configured {configured!r}, resolved {str(resolved)!r}, base {str(base)!r}: {error}", location)) from error
        digest = hashlib.sha256(data).hexdigest()
        filename = f"{digest}.{fmt}"
        files[filename] = data
        manifest["assets"][ref] = {"path": filename, "sha256": digest}
    return {"manifest": manifest, "files": files, "runtime": [ref for ref, declaration in declarations.items() if declaration.get("runtime") is True]}


def load_definition_assets(definition: Any, bindings: Any = None, *, prepared: Any = None) -> dict[str, Any]:
    prepared = prepare_assets(definition) if prepared is None else prepared
    static = {ref: {"type": "image", "format": Path(entry["path"]).suffix[1:], "data_base64": base64.b64encode(prepared["files"][entry["path"]]).decode("ascii")} for ref, entry in prepared["manifest"]["assets"].items()}
    return _merge_assets(static, bindings, prepared["runtime"])


def _merge_assets(static: dict[str, Any], bindings: Any, runtime: list[str]) -> dict[str, Any]:
    bound = validate_assets(bindings)
    duplicates = set(static) & set(bound)
    if duplicates:
        _error("static/runtime asset collision: " + ", ".join(sorted(duplicates)))
    missing = set(runtime) - set(bound)
    if missing:
        _error("missing runtime asset bindings: " + ", ".join(sorted(missing)))
    assets = {**static, **bound}
    # Only declarations are logical IDs; all other bindings are native reference keys.
    for ref in [*static, *runtime]:
        token = f"<asset:{ref}>"
        if token in assets:
            _error(f"asset {ref!r} collides with native reference {token!r}")
        assets[token] = assets.pop(ref)
    return validate_assets(assets)


def load_asset_bundle(manifest: dict[str, Any], module_file: str, bundle_name: str, runtime: list[str], bindings: Any = None, *, bundle_base: str | Path | None = None) -> dict[str, Any]:
    base = Path(bundle_base) if bundle_base is not None else Path(module_file).parent / bundle_name
    static: dict[str, Any] = {}
    for ref, entry in manifest["assets"].items():
        relative = Path(entry["path"])
        if relative.is_absolute() or len(relative.parts) != 1:
            _error(f"invalid asset bundle path for {ref!r}")
        try:
            data = (base / relative).read_bytes()
        except OSError as error:
            _error(f"cannot read bundled asset {ref!r}: {error}")
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            _error(f"bundled asset {ref!r} hash mismatch")
        fmt = image_format(data)
        static[ref] = {"type": "image", "format": fmt, "data_base64": base64.b64encode(data).decode("ascii")}
    return _merge_assets(static, bindings, runtime)
