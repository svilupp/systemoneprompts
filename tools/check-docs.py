#!/usr/bin/env python3
"""Check the minimum documentation surfaces shipped by the repository."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    ROOT / "README.md",
    ROOT / "PLAN_packages.md",
    ROOT / "docs" / "SPEC.md",
    ROOT / "docs" / "SPEC.html",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "compatibility.md",
    ROOT / "docs" / "releasing.md",
    ROOT / "packages" / "typescript" / "docs" / "SPEC.html",
    ROOT / "packages" / "python" / "docs" / "SPEC.html",
)


def main() -> int:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED if not path.is_file()]
    if missing:
        print("missing documentation: " + ", ".join(missing))
        return 1
    expected = (ROOT / "docs" / "SPEC.html").read_bytes()
    for package in (ROOT / "packages" / "typescript", ROOT / "packages" / "python"):
        if (package / "docs" / "SPEC.html").read_bytes() != expected:
            print(f"stale package specification: {package / 'docs' / 'SPEC.html'}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
