"""Warm-pool activation orchestration tests (#28).

Pins the security-critical control flow of ``raes_gcp_activate.activate_raes_range_cell``
with a fake :class:`ActivationOps`: scrub happens before realize, realized members
are returned on success, and a failed negative verification fails closed (the
generation is never handed over). The concrete GCE leaf composition is exercised
live on a real range (the repo's verification norm for provisioner cloud effects).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from shared.raes.operation_input import RaesInputBindings, build_raes_operation_input
from shared.warm_pool.activation_input import (
    ActivationClaimant,
    ActivationGeneration,
    build_activation_input,
    parse_activation_input,
)

from raes_gcp_activate import ActivationError, ActivationResult, activate_raes_range_cell


def _activation():
    raes_input = build_raes_operation_input(
        plan={},
        bindings=RaesInputBindings(delivery=()),
        image_candidates={},
        range_backend="gce",
        instantiation_purpose="live_fire",
        legacy_range_id=1001,
    )
    payload = build_activation_input(
        claimant=ActivationClaimant(user_id=42, username="claimant@example.com", workspace_id=7),
        generation=ActivationGeneration(
            range_source="mission-control",
            instantiation_purpose="live_fire",
            range_backend="gce",
            legacy_range_id=1001,
            compatibility_digest="sha256:" + "a" * 64,
            prepared_generation_fence=str(uuid4()),
        ),
        raes_input=raes_input,
    )
    return parse_activation_input(payload)


class _FakeOps:
    def __init__(self, *, revoked: bool = True, members: list | None = None):
        self.calls: list[str] = []
        self._revoked = revoked
        self._members = members if members is not None else [{"target_address": "n1", "channel": "ssh"}]

    def scrub_pre_claim_access(self, activation, prepared_generation):
        self.calls.append("scrub")

    def realize_claimant_access(self, activation, activate_generation):
        self.calls.append("realize")
        return ActivationResult(members=self._members, completion={"resources": []})

    def prior_access_revoked(self, activation, prepared_generation):
        self.calls.append("verify")
        return self._revoked


def test_scrub_precedes_realize_precedes_verify():
    ops = _FakeOps()
    result = activate_raes_range_cell(
        activation=_activation(), prepared_generation=uuid4(), activate_generation=uuid4(), ops=ops
    )
    assert ops.calls == ["scrub", "realize", "verify"]
    assert result.members == [{"target_address": "n1", "channel": "ssh"}]


def test_failed_negative_verification_fails_closed():
    ops = _FakeOps(revoked=False)
    activation = _activation()
    with pytest.raises(ActivationError) as exc:
        activate_raes_range_cell(
            activation=activation, prepared_generation=uuid4(), activate_generation=uuid4(), ops=ops
        )
    assert "revoked" in str(exc.value)
    # Scrub and realize ran, verify failed; the generation is not handed over.
    assert ops.calls == ["scrub", "realize", "verify"]


def test_scrub_failure_aborts_before_realize():
    class _ScrubBoom(_FakeOps):
        def scrub_pre_claim_access(self, activation, prepared_generation):
            self.calls.append("scrub")
            raise RuntimeError("scrub failed")

    ops = _ScrubBoom()
    activation = _activation()
    with pytest.raises(RuntimeError):
        activate_raes_range_cell(
            activation=activation, prepared_generation=uuid4(), activate_generation=uuid4(), ops=ops
        )
    # Realize never runs if scrub fails: no window with both credentials valid.
    assert ops.calls == ["scrub"]
