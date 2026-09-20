"""Load a hyphenated `*_generated.py` sitting next to an example `run.py`."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from systemoneprompts.provider import load_dotenv


def load_generated(here: Path, name: str) -> ModuleType:
    load_dotenv(str(here.parents[1]))
    path = here / name
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load generated module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
