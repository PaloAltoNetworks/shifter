"""Generated installation schema stays byte-for-byte derived from shared models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.model_access import model_access_catalog_schema


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_installation_schema_matches_canonical_shared_models(version):
    path = Path(__file__).parents[4] / f"installation/published_contract/model-access-policy.{version}.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == model_access_catalog_schema(version)
