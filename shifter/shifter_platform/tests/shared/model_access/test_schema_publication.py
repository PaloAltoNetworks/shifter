"""Generated installation schema stays byte-for-byte derived from shared models."""

from __future__ import annotations

import json
from pathlib import Path

from shared.model_access import model_access_catalog_schema


def test_installation_schema_matches_canonical_shared_models():
    path = Path(__file__).parents[4] / "installation/published_contract/model-access-policy.v1.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == model_access_catalog_schema()
