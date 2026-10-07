"""Expand shared adapter cases from one baseline and explicit field changes."""
import copy
import json
from pathlib import Path


def provider_fixtures(name):
    corpus = Path(__file__).resolve().parents[1] / "conformance/v1/providers"
    document = json.loads((corpus / f"{name}.json").read_text())
    fixtures = []
    for variant in document["cases"]:
        fixture = copy.deepcopy(document["base"])
        for path in variant.get("remove", []):
            parent = fixture
            for key in path[:-1]:
                parent = parent[key]
            del parent[path[-1]]
        for path, value in variant["set"]:
            parent = fixture
            for key in path[:-1]:
                parent = parent[key]
            parent[path[-1]] = copy.deepcopy(value)
        fixtures.append(fixture)
    return fixtures
