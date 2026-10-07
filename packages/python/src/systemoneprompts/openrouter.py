"""OpenRouter endpoint normalization and cache scope."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit

from .diagnostics import SystemOnePromptsError, diagnostic


def openrouter_base_url(value: str | None = None) -> str:
    normalized = (value if value is not None else os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/alpha").strip().rstrip("/")
    normalized = normalized.removesuffix("/decisions")
    try:
        url = urlsplit(normalized)
        valid = url.scheme in ("http", "https") and bool(url.hostname) and not (url.username or url.password or url.query or url.fragment)
        _ = url.port
    except ValueError:
        valid = False
    if not valid:
        raise SystemOnePromptsError(diagnostic("error", "base-url", "base_url must be an HTTP(S) URL without credentials, query, or fragment"))
    return normalized


def openrouter_cache_dir(*, dir: str | None = None, base_url: str | None = None) -> str:
    origin = hashlib.sha256(openrouter_base_url(base_url).encode()).hexdigest()
    return str(Path(dir or Path.cwd() / ".systemoneprompts") / "providers" / "openrouter-decisions" / "v1" / origin / "cache")
