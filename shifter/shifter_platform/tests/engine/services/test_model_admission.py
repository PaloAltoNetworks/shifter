"""Engine-owned required-model admission composition (PLAT-202, #2119).

These cover the Engine's composition of catalog profile lookup, the no-sharing
path, and delegation to the fail-closed decision. Sharing-overlap contention
against real bindings is covered by the PostgreSQL integration lane.
"""

from __future__ import annotations

import pytest

from engine.services import admit_range_model_access
from shared.model_access import (
    AccessLimits,
    AllocationStrategy,
    ModelAdmissionOutcome,
    ModelAdmissionReason,
    ScenarioNeed,
    ScenarioNeedProjection,
    validate_catalog,
)
from shared.model_access.admission import EventModelDemand
from shared.model_access.digest import compute_digest

pytestmark = pytest.mark.django_db

_DIGEST = "sha256:" + "a" * 64
_SUBJECT = {"owner": "deployment", "reference": "range:r1"}


def _limits() -> dict:
    return {
        "max_request_seconds": 120,
        "max_request_bytes": 1_000_000,
        "max_input_tokens": 8_000,
        "max_output_tokens": 2_000,
        "max_requests_per_window": 60,
        "request_window_seconds": 60,
        "max_spend_micro_units": 5_000_000,
        "currency": "USD",
        "max_concurrent_requests": 2,
    }


def _catalog(*, enabled=True):
    payload = {
        "contract_version": "model-access-policy/v1",
        "deployment_id": "11111111-1111-4111-8111-111111111111",
        "enabled": enabled,
        "profiles": [
            {
                "profile_id": "coding",
                "capabilities": ["messages", "token-count"],
                "allowed_strategies": ["fixed-v1", "weighted-rendezvous-v1"],
                "data_regions": ["europe-west4"],
                "limits": _limits(),
            }
        ],
        "quota_pools": [
            {
                "quota_pool_id": "vertex-tokens-eu",
                "provider_adapter_id": "vertex-v1",
                "provider_quota_identity": "project:models-a/region:europe-west4/model:claude",
                "dimension": "input_tokens",
                "unit": "tokens/minute",
                "limit": 1000000,
            }
        ],
        "price_schedules": [
            {
                "price_schedule_id": "vertex-2026-09",
                "currency": "USD",
                "valid_until": "2026-10-01T00:00:00Z",
                "prices": [{"component": "input_tokens", "unit_denominator": 1000000, "price_micro_units": 3000000}],
            }
        ],
        "shards": [
            {
                "shard_id": "vertex-primary",
                "provider_adapter_id": "vertex-v1",
                "compute_target_ref": {"owner": "installation", "reference": "gcp:gce-primary"},
                "model_project_ref": {"owner": "deployment", "reference": "project:models-a"},
                "model_account_ref": {"owner": "deployment", "reference": "billing:models-a"},
                "dynamic_secret_project_ref": {"owner": "deployment", "reference": "project:secrets-a"},
                "broker_workload_identity_ref": {"owner": "deployment", "reference": "gsa:model-broker"},
                "credential_ref": {"owner": "broker", "reference": "impersonate:gsa/model-invoke"},
                "region": "europe-west4",
                "provider_model": "publishers/anthropic/models/claude-sonnet",
                "provider_model_version": "20260901",
                "protocol": "anthropic-messages/2023-06-01",
                "capabilities": ["messages", "token-count"],
                "billing_components": ["input_tokens"],
                "quota_pool_ids": ["vertex-tokens-eu"],
                "weight": 1,
                "enabled": True,
            }
        ],
        "aliases": [
            {
                "logical_alias": "coding-main",
                "profile_id": "coding",
                "strategy": "fixed-v1",
                "affinity": "per_range",
                "eligible_shard_ids": ["vertex-primary"],
                "price_schedule_id": "vertex-2026-09",
            }
        ],
        "sharing_pools": [],
        "sharing_bindings": [],
    }
    payload["digest"] = compute_digest(payload)
    return validate_catalog(payload)


def _need(*, required=True, profile_id="coding") -> ScenarioNeed:
    return ScenarioNeed(
        contract_version="model-access-scenario/v1",
        scenario_digest=_DIGEST,
        workload_role="participant",
        profile_id=profile_id,
        required=required,
        required_capabilities=("messages",),
        allowed_capabilities=("messages",),
        allowed_strategies=(AllocationStrategy.FIXED_V1,),
        data_regions=("europe-west4",),
        limits=AccessLimits.model_validate(_limits()),
    )


def _projection(need, *, digest_verified=True) -> ScenarioNeedProjection:
    return ScenarioNeedProjection(workload_role="participant", need=need, digest_verified=digest_verified)


def _demand() -> EventModelDemand:
    return EventModelDemand(
        workload_role="participant",
        expected_concurrency=4,
        per_participant_requests=100,
        per_participant_input_tokens=4_000,
        per_participant_output_tokens=1_000,
        allowed_strategy=AllocationStrategy.FIXED_V1,
    )


def _admit(**overrides):
    kwargs = {
        "subject": _SUBJECT,
        "need_projections": {"participant": _projection(_need())},
        "demands": {"participant": _demand()},
        "egress_permits_model": True,
        "catalog": _catalog(),
    }
    kwargs.update(overrides)
    return admit_range_model_access(**kwargs)[0]


def test_required_need_with_matching_profile_and_no_sharing_is_admitted():
    result = _admit()
    assert result.outcome is ModelAdmissionOutcome.ADMITTED
    assert result.reason is ModelAdmissionReason.ADMITTED


def test_unconfigured_catalog_denies_required_need():
    result = _admit(catalog=None)
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.POLICY_UNAVAILABLE


def test_stale_pack_digest_denies_required_need():
    result = _admit(need_projections={"participant": _projection(_need(), digest_verified=False)})
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.DIGEST_MISMATCH


def test_no_authored_need_is_admitted_without_gate():
    result = _admit(need_projections={}, demands={"participant": _demand()})
    assert result.outcome is ModelAdmissionOutcome.ADMITTED
    assert result.reason is ModelAdmissionReason.NO_BINDING


def test_profile_absent_from_catalog_denies_required_need():
    result = _admit(need_projections={"participant": _projection(_need(profile_id="missing"))})
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.POLICY_UNAVAILABLE


def test_zero_egress_denies_required_external_need():
    result = _admit(egress_permits_model=False)
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.EGRESS_INCOMPATIBLE


# --- sharing overlap fold (overlap correctness lives in test_effective_policy) ---


def _fake_policy(*, contributions, stale, admissible, effective_profile=None):
    from types import SimpleNamespace

    return SimpleNamespace(
        contributions=contributions,
        stale=stale,
        admissible=admissible,
        effective_profile=effective_profile,
    )


def test_sharing_conflict_denies_required_need(monkeypatch):
    monkeypatch.setattr(
        "engine.services._sharing.preview_effective_policy",
        lambda **_kwargs: _fake_policy(contributions=("c",), stale=False, admissible=False),
    )
    result = _admit()
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.SHARING_CONFLICT


def test_stale_membership_is_indeterminate_for_required_need(monkeypatch):
    monkeypatch.setattr(
        "engine.services._sharing.preview_effective_policy",
        lambda **_kwargs: _fake_policy(contributions=("c",), stale=True, admissible=False),
    )
    result = _admit()
    assert result.outcome is ModelAdmissionOutcome.INDETERMINATE
    assert result.reason is ModelAdmissionReason.AUTHORITY_UNAVAILABLE


def test_admissible_sharing_overlap_permits_required_need(monkeypatch):
    monkeypatch.setattr(
        "engine.services._sharing.preview_effective_policy",
        lambda **_kwargs: _fake_policy(contributions=("c",), stale=False, admissible=True),
    )
    result = _admit()
    assert result.outcome is ModelAdmissionOutcome.ADMITTED


def test_authority_unavailable_when_sharing_resolution_raises(monkeypatch):
    def _boom(**_kwargs):
        raise RuntimeError("authority down")

    monkeypatch.setattr("engine.services._sharing.preview_effective_policy", _boom)
    result = _admit()
    assert result.outcome is ModelAdmissionOutcome.INDETERMINATE
    assert result.reason is ModelAdmissionReason.AUTHORITY_UNAVAILABLE


def test_disabled_catalog_denies_required_need():
    result = _admit(catalog=_catalog(enabled=False))
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.POLICY_UNAVAILABLE


def test_admissible_sharing_profile_restriction_denies_required_capability(monkeypatch):
    # Sharing overlap is internally admissible but its compiled profile restricts
    # capabilities below the scenario need (needs "tools", sharing offers only
    # "messages"): admission must deny rather than pass on the boolean alone.
    from shared.model_access import EffectiveProfile

    restricted = EffectiveProfile(
        profile_id="coding",
        required=True,
        capabilities=("messages",),
        allowed_strategies=(AllocationStrategy.FIXED_V1,),
        data_regions=("europe-west4",),
        limits=AccessLimits.model_validate(_limits()),
    )
    monkeypatch.setattr(
        "engine.services._sharing.preview_effective_policy",
        lambda **_kwargs: _fake_policy(
            contributions=("c",), stale=False, admissible=True, effective_profile=restricted
        ),
    )
    # The catalog "coding" profile allows both messages and token-count, so the
    # need passes the catalog intersection; only the sharing profile forecloses it.
    need = _need().model_copy(
        update={"required_capabilities": ("token-count",), "allowed_capabilities": ("messages", "token-count")}
    )
    result = _admit(need_projections={"participant": _projection(need)})
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.REQUIRED_CAPABILITY_UNAVAILABLE
