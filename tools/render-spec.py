#!/usr/bin/env python3
"""Render the small normative Markdown contract without a documentation dependency."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "SPEC.md"
OUTPUT = ROOT / "docs" / "SPEC.html"


def inline(text: str) -> str:
    rendered = html.escape(text, quote=False)
    rendered = re.sub(r"`([^`]+)`", r"<code>\1</code>", rendered)
    rendered = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: f'<a href="{html.escape(match.group(2), quote=True)}">{match.group(1)}</a>',
        rendered,
    )
    return rendered


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")


def render(markdown: str) -> str:
    body: list[str] = []
    paragraph: list[str] = []
    in_list = False
    in_code = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            body.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("```"):
            flush_paragraph()
            close_list()
            if in_code:
                body.append("</code></pre>")
            else:
                body.append("<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            body.append(html.escape(line))
            body.append("\n")
            continue
        if not line:
            flush_paragraph()
            close_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            text = heading.group(2)
            level = len(heading.group(1))
            body.append(f'<h{level} id="{slug(text)}">{inline(text)}</h{level}>')
            continue
        if line.startswith("- "):
            flush_paragraph()
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{inline(line[2:])}</li>")
            continue
        close_list()
        paragraph.append(line)

    flush_paragraph()
    close_list()
    return "\n".join(body)


def document(markdown: str) -> str:
    title = next(
        (line[2:].strip() for line in markdown.splitlines() if line.startswith("# ")),
        "systemoneprompts specification",
    )
    content = render(markdown)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ max-width: 920px; margin: 3rem auto; padding: 0 1.25rem; font: 16px/1.6 system-ui, sans-serif; }}
    code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    code {{ padding: .1rem .25rem; border-radius: .25rem; background: #8882; }}
    pre {{ overflow-x: auto; padding: 1rem; border-radius: .5rem; background: #8882; }}
    h1, h2, h3 {{ line-height: 1.2; margin-top: 2rem; }}
    a {{ color: #268bd2; }}
  </style>
</head>
<body>
{content}
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = document(SOURCE.read_text(encoding="utf-8"))
    if args.check:
        return int(
            not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected
        )
    OUTPUT.write_text(expected, encoding="utf-8")
    for package in (ROOT / "packages" / "typescript", ROOT / "packages" / "python"):
        destination = package / "docs" / "SPEC.html"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
