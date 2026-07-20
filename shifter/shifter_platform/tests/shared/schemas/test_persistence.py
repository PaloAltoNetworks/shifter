"""Tests for shared.schemas.persistence."""

import pytest

from shared.schemas import RangeSpec
from shared.schemas.persistence import (
    SPEC_VERSION,
    unwrap_persisted_spec,
    validate_persisted_spec,
    wrap_persisted_spec,
)


def test_wrap_adds_discriminator():
    spec = RangeSpec(scenario_id="basic", user_id=1, subnets=[])
    wrapped = wrap_persisted_spec("range_spec", spec)

    assert wrapped["spec_schema"] == "range_spec"
    assert wrapped["spec_version"] == SPEC_VERSION
    assert wrapped["payload"]["scenario_id"] == "basic"


def test_unwrap_round_trip():
    spec = RangeSpec(scenario_id="basic", user_id=1, subnets=[])
    wrapped = wrap_persisted_spec("range_spec", spec)
    payload = unwrap_persisted_spec(wrapped)

    assert payload["scenario_id"] == "basic"
    assert "spec_schema" not in payload


def test_legacy_blob_passthrough():
    legacy = {"scenario_id": "basic", "user_id": 1, "subnets": []}
    assert unwrap_persisted_spec(legacy) == legacy


def test_validate_persisted_spec_new_format():
    spec = RangeSpec(scenario_id="basic", user_id=1, subnets=[])
    wrapped = wrap_persisted_spec("range_spec", spec)
    validated = validate_persisted_spec(wrapped, "range_spec")

    assert isinstance(validated, RangeSpec)
    assert validated.scenario_id == "basic"


def test_validate_persisted_spec_legacy_format():
    legacy = {"scenario_id": "basic", "user_id": 1, "subnets": []}
    validated = validate_persisted_spec(legacy, "range_spec")

    assert isinstance(validated, RangeSpec)


def test_validate_wrong_slug_raises():
    spec = RangeSpec(scenario_id="basic", user_id=1, subnets=[])
    wrapped = wrap_persisted_spec("range_spec", spec)

    with pytest.raises(ValueError, match="spec_schema mismatch"):
        validate_persisted_spec(wrapped, "instance_spec")


def test_validate_unsupported_version_raises():
    spec = RangeSpec(scenario_id="basic", user_id=1, subnets=[])
    wrapped = wrap_persisted_spec("range_spec", spec)
    wrapped["spec_version"] = "999"

    with pytest.raises(ValueError, match="Unsupported spec_version"):
        validate_persisted_spec(wrapped, "range_spec")
