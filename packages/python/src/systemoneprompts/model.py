"""Pure model selection helpers shared by future provider integrations."""

from __future__ import annotations

import os
from collections.abc import Mapping

DEFAULT_MODEL = "jev-latest"


def read_env_model(env: Mapping[str, str | None] | None = None) -> str | None:
    """Return the first nonblank model environment value."""
    values = os.environ if env is None else env
    model = values.get("TYPESAFE_MODEL")
    if isinstance(model, str) and model.strip():
        return model.strip()
    fallback = values.get("TYPESAFE_DEFAULT_MODEL")
    return fallback.strip() if isinstance(fallback, str) and fallback.strip() else None


def resolve_model(
    env_model: str | None = None,
    definition_model: str | None = None,
    override: str | None = None,
    *,
    default: str = DEFAULT_MODEL,
) -> str:
    """Resolve default/environment, definition, and call-site model values."""
    resolved = default.strip() or DEFAULT_MODEL
    for candidate in (env_model, definition_model, override):
        if isinstance(candidate, str) and candidate.strip():
            resolved = candidate.strip()
    return resolved


__all__ = ["DEFAULT_MODEL", "read_env_model", "resolve_model"]
