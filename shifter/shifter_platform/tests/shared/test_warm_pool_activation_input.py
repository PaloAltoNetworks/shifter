"""Tests for ``shared.warm_pool.activation_input`` (#28).

The activation input is the only warm operation carrying a claimant identity; it
must be a closed, bounded, reference-only projection. These tests pin:

- round-trip build -> parse;
- fail-closed on unknown/missing keys, wrong schema tag, non-positive identity,
  over-long username, blank fence;
- no secret/inventory/policy field is accepted (extra keys rejected).
"""

from __future__ import annotations

import pytest

from shared.raes.operation_input import RaesInputBindings, build_raes_operation_input
from shared.warm_pool.activation_input import (
    ACTIVATION_SCHEMA,
    ActivationClaimant,
    ActivationGeneration,
    ActivationInputError,
    build_activation_input,
    parse_activation_input,
)


def _raes_input():
    return build_raes_operation_input(
        plan={},
        bindings=RaesInputBindings(delivery=()),
        image_candidates={},
        range_backend="gce",
        instantiation_purpose="live_fire",
        legacy_range_id=1001,
    )


def _payload(**overrides):
    base = {
        "claimant_user_id": 42,
        "claimant_username": "claimant@example.com",
        "workspace_id": 7,
        "range_source": "mission-control",
        "instantiation_purpose": "live_fire",
        "range_backend": "gce",
        "legacy_range_id": 1001,
        "compatibility_digest": "sha256:" + "a" * 64,
        "prepared_generation_fence": "7f000000-0000-4000-8000-000000000001",
        "raes_input": _raes_input(),
    }
    base.update(overrides)
    return base


def _build_from_payload(payload):
    """Build the activation payload from a flat ``_payload`` dict via grouped inputs."""
    return build_activation_input(
        claimant=ActivationClaimant(
            user_id=payload["claimant_user_id"],
            username=payload["claimant_username"],
            workspace_id=payload["workspace_id"],
        ),
        generation=ActivationGeneration(
            range_source=payload["range_source"],
            instantiation_purpose=payload["instantiation_purpose"],
            range_backend=payload["range_backend"],
            legacy_range_id=payload["legacy_range_id"],
            compatibility_digest=payload["compatibility_digest"],
            prepared_generation_fence=payload["prepared_generation_fence"],
        ),
        raes_input=payload["raes_input"],
    )


class TestRoundTrip:
    def test_build_then_parse(self):
        payload = _build_from_payload(_payload())
        parsed = parse_activation_input(payload)
        assert parsed.claimant_user_id == 42
        assert parsed.claimant_username == "claimant@example.com"
        assert parsed.range_backend == "gce"
        assert payload["schema"] == ACTIVATION_SCHEMA

    def test_parsed_carries_full_projection(self):
        parsed = parse_activation_input(_build_from_payload(_payload()))
        assert parsed.workspace_id == 7
        assert parsed.range_source == "mission-control"
        assert parsed.instantiation_purpose == "live_fire"
        assert parsed.legacy_range_id == 1001
        assert parsed.prepared_generation_fence == "7f000000-0000-4000-8000-000000000001"
        assert parsed.raes_input.range_backend == "gce"


class TestFailClosed:
    def test_unknown_key_rejected(self):
        payload = _payload()
        payload["schema"] = ACTIVATION_SCHEMA
        payload["secret_token"] = "nope"
        with pytest.raises(ActivationInputError) as exc:
            parse_activation_input(payload)
        assert "unexpected" in str(exc.value)

    def test_missing_key_rejected(self):
        payload = _build_from_payload(_payload())
        del payload["claimant_user_id"]
        with pytest.raises(ActivationInputError) as exc:
            parse_activation_input(payload)
        assert "missing" in str(exc.value)

    def test_wrong_schema_rejected(self):
        payload = _build_from_payload(_payload())
        payload["schema"] = "range-warm-activation/v2"
        with pytest.raises(ActivationInputError):
            parse_activation_input(payload)

    @pytest.mark.parametrize("bad", [0, -1, True, "5"])
    def test_non_positive_identity_rejected(self, bad):
        payload = _payload(claimant_user_id=bad)
        with pytest.raises(ActivationInputError):
            _build_from_payload(payload)

    def test_over_long_username_rejected(self):
        payload = _payload(claimant_username="x" * 300)
        with pytest.raises(ActivationInputError):
            _build_from_payload(payload)

    def test_blank_fence_rejected(self):
        payload = _payload(prepared_generation_fence="  ")
        with pytest.raises(ActivationInputError):
            _build_from_payload(payload)

    def test_invalid_raes_input_rejected(self):
        payload = _payload(raes_input={"not": "a-valid-raes-projection"})
        with pytest.raises(ActivationInputError):
            _build_from_payload(payload)

    def test_non_mapping_rejected(self):
        with pytest.raises(ActivationInputError):
            parse_activation_input(["not", "a", "mapping"])
