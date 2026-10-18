#!/usr/bin/env python3
"""Check the minimum documentation surfaces shipped by the repository."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_FIXTURES = {".toml", ".json", ".jsonl", ".png", ".jpg", ".jpeg"}
REQUIRED = (
    ROOT / "README.md",
    ROOT / "docs" / "SPEC.md",
    ROOT / "docs" / "SPEC.html",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "compatibility.md",
    ROOT / "docs" / "releasing.md",
    ROOT / "packages" / "typescript" / "docs" / "SPEC.html",
    ROOT / "packages" / "python" / "docs" / "SPEC.html",
)


def example_fixture_files(examples: Path) -> dict[Path, Path]:
    # Generated module naming is idiomatic per language; bundle content is shared.
    return {
        Path(str(path.relative_to(examples)).replace("_generated.assets/", ".generated.assets/")): path
        for path in examples.rglob("*")
        if path.is_file() and path.suffix in EXAMPLE_FIXTURES
    }


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
    ts_examples = ROOT / "packages" / "typescript" / "examples"
    py_examples = ROOT / "packages" / "python" / "examples"
    ts_fixtures = example_fixture_files(ts_examples)
    py_fixtures = example_fixture_files(py_examples)
    if ts_fixtures.keys() != py_fixtures.keys():
        only_ts = ", ".join(str(path) for path in sorted(ts_fixtures.keys() - py_fixtures.keys())) or "(none)"
        only_py = ", ".join(str(path) for path in sorted(py_fixtures.keys() - ts_fixtures.keys())) or "(none)"
        print(f"example fixtures differ: only TypeScript {only_ts}; only Python {only_py}")
        return 1
    for rel in sorted(ts_fixtures):
        if ts_fixtures[rel].read_bytes() != py_fixtures[rel].read_bytes():
            print(f"example fixture mismatch: {rel}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
