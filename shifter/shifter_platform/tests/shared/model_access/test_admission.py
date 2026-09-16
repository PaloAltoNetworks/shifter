"""Fail-closed required-model admission decision core (PLAT-202, #2119).

These are Django-free unit tests for the pure authorization decision that every
launch family routes required model access through. Overlap/sharing correctness
lives in ``test_effective_policy.py``; here ``sharing_admissible`` is the folded
input, so these tests focus on the fail-closed vs. optional-absent behaviour.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.model_access import AccessLimits, AllocationStrategy, EffectiveProfile, ModelProfile, ScenarioNeed
from shared.model_access.admission import (
    EventModelDemand,
    ModelAdmissionOutcome,
    ModelAdmissionReason,
    ModelAdmissionResult,
    ScenarioNeedProjection,
    decide_model_admission,
)

_DIGEST = "sha256:" + "a" * 64
_OTHER_DIGEST = "sha256:" + "b" * 64


def _limits(**overrides) -> AccessLimits:
    values = {
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
    values.update(overrides)
    return AccessLimits.model_validate(values)


def _profile(**overrides) -> ModelProfile:
    values = {
        "profile_id": "coding",
        "capabilities": ("messages", "token-count"),
        "allowed_strategies": (AllocationStrategy.FIXED_V1, AllocationStrategy.WEIGHTED_RENDEZVOUS_V1),
        "data_regions": ("europe-west4",),
        "limits": _limits(),
    }
    values.update(overrides)
    return ModelProfile(**values)


def _need(*, required: bool = True, digest: str = _DIGEST, **overrides) -> ScenarioNeed:
    values = {
        "contract_version": "model-access-scenario/v1",
        "scenario_digest": digest,
        "workload_role": "participant",
        "profile_id": "coding",
        "required": required,
        "required_capabilities": ("messages",),
        "allowed_capabilities": ("messages",),
        "allowed_strategies": (AllocationStrategy.FIXED_V1,),
        "data_regions": ("europe-west4",),
        "limits": _limits(),
    }
    values.update(overrides)
    return ScenarioNeed(**values)


def _projection(need: ScenarioNeed | None, *, digest_verified: bool = True) -> ScenarioNeedProjection:
    return ScenarioNeedProjection(workload_role="participant", need=need, digest_verified=digest_verified)


def _demand(**overrides) -> EventModelDemand:
    values = {
        "workload_role": "participant",
        "expected_concurrency": 4,
        "per_participant_requests": 100,
        "per_participant_input_tokens": 4_000,
        "per_participant_output_tokens": 1_000,
        "allowed_strategy": AllocationStrategy.FIXED_V1,
    }
    values.update(overrides)
    return EventModelDemand(**values)


def _decide(**overrides) -> ModelAdmissionResult:
    kwargs = {
        "projection": _projection(_need()),
        "demand": _demand(),
        "profile": _profile(),
        "sharing_admissible": None,
        "egress_permits_model": True,
        "authority_available": True,
    }
    kwargs.update(overrides)
    return decide_model_admission(**kwargs)


# --- DTO validation ---------------------------------------------------------


def test_event_model_demand_is_closed_and_rejects_provider_fields():
    with pytest.raises(ValidationError):
        EventModelDemand(
            workload_role="participant",
            expected_concurrency=4,
            per_participant_requests=100,
            per_participant_input_tokens=4_000,
            per_participant_output_tokens=1_000,
            allowed_strategy=AllocationStrategy.FIXED_V1,
            provider="vertex",  # not a permitted member
        )


def test_event_model_demand_requires_positive_quantities():
    with pytest.raises(ValidationError):
        _demand(expected_concurrency=0)


# --- no binding = no gate ---------------------------------------------------


def test_no_binding_admits_with_no_gate():
    result = _decide(projection=_projection(None))
    assert result.outcome is ModelAdmissionOutcome.ADMITTED
    assert result.reason is ModelAdmissionReason.NO_BINDING
    assert result.required is False


# --- digest binding ---------------------------------------------------------


def test_required_need_with_stale_pack_digest_fails_closed():
    result = _decide(projection=_projection(_need(required=True), digest_verified=False))
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.DIGEST_MISMATCH
    assert result.required is True


def test_optional_need_with_stale_pack_digest_does_not_block():
    result = _decide(projection=_projection(_need(required=False), digest_verified=False))
    assert result.outcome is ModelAdmissionOutcome.ADMITTED


# --- fail-closed required paths ---------------------------------------------


def test_required_need_without_policy_is_denied():
    result = _decide(profile=None)
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.POLICY_UNAVAILABLE


def test_required_need_with_zero_egress_is_denied():
    result = _decide(egress_permits_model=False)
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.EGRESS_INCOMPATIBLE


def test_required_capability_outside_profile_is_denied():
    need = _need(required_capabilities=("tools",), allowed_capabilities=("messages", "tools"))
    result = _decide(projection=_projection(need))
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.REQUIRED_CAPABILITY_UNAVAILABLE


def test_required_need_empty_intersection_is_denied():
    profile = _profile(data_regions=("us-central1",))
    result = _decide(profile=profile)
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.EMPTY_INTERSECTION


def test_required_need_with_unadmissible_sharing_is_denied():
    result = _decide(sharing_admissible=False)
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.SHARING_CONFLICT


def test_required_need_without_authority_is_indeterminate():
    result = _decide(authority_available=False)
    assert result.outcome is ModelAdmissionOutcome.INDETERMINATE
    assert result.reason is ModelAdmissionReason.AUTHORITY_UNAVAILABLE


def test_demand_strategy_outside_need_is_denied():
    demand = _demand(allowed_strategy=AllocationStrategy.WEIGHTED_RENDEZVOUS_V1)
    result = _decide(demand=demand)
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.STRATEGY_NOT_ALLOWED


# --- admitted / optional-absent ---------------------------------------------


def test_required_need_all_satisfied_is_admitted():
    result = _decide()
    assert result.outcome is ModelAdmissionOutcome.ADMITTED
    assert result.reason is ModelAdmissionReason.ADMITTED
    assert result.required is True


def test_admitted_with_sharing_admissible_true():
    result = _decide(sharing_admissible=True)
    assert result.outcome is ModelAdmissionOutcome.ADMITTED


def test_optional_need_empty_intersection_is_visible_absence():
    profile = _profile(data_regions=("us-central1",))
    result = _decide(projection=_projection(_need(required=False)), profile=profile)
    assert result.outcome is ModelAdmissionOutcome.ADMITTED
    assert result.reason is ModelAdmissionReason.OPTIONAL_ABSENT
    assert result.required is False


# --- sharing effective-profile intersection ---------------------------------


def _sharing_profile(**overrides) -> EffectiveProfile:
    values = {
        "profile_id": "coding",
        "required": True,
        "capabilities": ("messages", "token-count"),
        "allowed_strategies": (AllocationStrategy.FIXED_V1,),
        "data_regions": ("europe-west4",),
        "limits": _limits(),
    }
    values.update(overrides)
    return EffectiveProfile(**values)


def test_sharing_profile_restricting_required_capability_denies():
    need = _need(required_capabilities=("token-count",), allowed_capabilities=("messages", "token-count"))
    result = _decide(projection=_projection(need), sharing_profile=_sharing_profile(capabilities=("messages",)))
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.REQUIRED_CAPABILITY_UNAVAILABLE


def test_sharing_profile_for_a_different_profile_conflicts():
    result = _decide(sharing_profile=_sharing_profile(profile_id="other"))
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.SHARING_CONFLICT


def test_sharing_profile_disjoint_region_denies():
    result = _decide(sharing_profile=_sharing_profile(data_regions=("us-central1",)))
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.EMPTY_INTERSECTION


def test_compatible_sharing_profile_admits():
    result = _decide(sharing_profile=_sharing_profile())
    assert result.outcome is ModelAdmissionOutcome.ADMITTED


def test_sharing_profile_empty_capability_intersection_denies_even_with_no_required_caps():
    # required=True but no *required* capabilities; catalog allows messages, sharing
    # allows only token-count -> empty capability intersection must deny (a subset
    # check trivially passes for an empty required set).
    need = _need(required_capabilities=(), allowed_capabilities=("messages",))
    result = _decide(projection=_projection(need), sharing_profile=_sharing_profile(capabilities=("token-count",)))
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.EMPTY_INTERSECTION


def test_demand_strategy_outside_sharing_strategies_denies():
    demand = _demand(allowed_strategy=AllocationStrategy.FIXED_V1)
    profile = _profile(allowed_strategies=(AllocationStrategy.FIXED_V1, AllocationStrategy.WEIGHTED_RENDEZVOUS_V1))
    need = _need(allowed_strategies=(AllocationStrategy.FIXED_V1, AllocationStrategy.WEIGHTED_RENDEZVOUS_V1))
    sharing = _sharing_profile(allowed_strategies=(AllocationStrategy.WEIGHTED_RENDEZVOUS_V1,))
    result = _decide(projection=_projection(need), profile=profile, demand=demand, sharing_profile=sharing)
    assert result.outcome is ModelAdmissionOutcome.DENIED
    assert result.reason is ModelAdmissionReason.STRATEGY_NOT_ALLOWED
