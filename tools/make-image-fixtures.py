#!/usr/bin/env python3
"""Rebuild small synthetic transport fixtures; requires Pillow, never calls a model."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    output = ROOT / "conformance/v1/images"
    output.mkdir(parents=True, exist_ok=True)
    for name, present in (("rectangle", True), ("empty", False)):
        image = Image.new("RGB", (320, 320), "white")
        if present:
            ImageDraw.Draw(image).rectangle((80, 80, 239, 239), fill=(220, 30, 30))
        image.save(output / f"{name}.png", optimize=False)
        if present:
            image.save(output / f"{name}.jpg", "JPEG", quality=90, progressive=False)


if __name__ == "__main__":
    main()
