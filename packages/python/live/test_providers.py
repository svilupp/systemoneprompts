"""Package-local smoke uses the same probe and sample as the full provider matrix."""
import json
import os
from pathlib import Path

import pytest
from provider_probe import probe

from systemoneprompts.provider import load_dotenv

load_dotenv()
SAMPLE = json.loads((Path(__file__).resolve().parents[1] / "conformance/v1/providers/native-decisions.json").read_text())


@pytest.mark.parametrize("provider,model,key", [
    ("typesafe", "jev-latest", "TYPESAFE_API_KEY"),
    ("openai", "gpt-6-luna", "OPENAI_API_KEY"),
    ("openrouter", "~typesafe/jev-latest", "OPENROUTER_API_KEY"),
    ("openrouter", "openai/gpt-6-luna-decisions", "OPENROUTER_API_KEY"),
    ("cloudflare", "clef", "CLOUDFLARE_API_TOKEN"),
    ("cloudflare", "clef-flash", "CLOUDFLARE_API_TOKEN"),
])
def test_native_answers_and_cache(provider, model, key, monkeypatch):
    if not os.environ.get(key) or (provider == "cloudflare" and not os.environ.get("CLOUDFLARE_ACCOUNT_ID")):
        pytest.skip("Provider credentials unavailable")
    if provider == "typesafe":
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    result = probe({"provider": provider, "model": model, "key": key, "mode": "environment",
                    "state": SAMPLE["state"], "questions": SAMPLE["questions"]})
    assert result["status"] == "pass"
    assert result["networkCalls"] == 1
