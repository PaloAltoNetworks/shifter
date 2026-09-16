"""Fail-closed required-model admission decision (PLAT-202, #2119).

The PLAT-201 capacity helpers are deliberately best-effort: ``None`` means
"proceed". Required model access is different — it is an authorization decision
that must fail closed before dispatch. This module is the single pure decision
every launch family routes required model access through. It performs no I/O:
the Engine resolves the scenario-need projection, deployment profile, folded
sharing admissibility, egress posture and authority availability, then calls
``decide_model_admission`` to obtain a bounded, secret-free result.

Sharing overlap resolution itself lives in :mod:`shared.model_access.effective_policy`;
here ``sharing_admissible`` is its folded verdict so this module never restates
the precedence rules.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import StrictBool

from shared.model_access.catalog import ContractError
from shared.model_access.core_models import (
    AllocationStrategy,
    ClosedModel,
    EffectiveProfile,
    Identifier,
    ModelProfile,
    PositiveInt,
    ScenarioNeed,
)
from shared.model_access.policy import intersect_profile


class ModelAdmissionOutcome(StrEnum):
    """The three admission outcomes; only ADMITTED permits a launch to proceed."""

    ADMITTED = "admitted"
    DENIED = "denied"
    INDETERMINATE = "indeterminate"


class ModelAdmissionReason(StrEnum):
    """Bounded, safe reason codes; never a raw provider error or rejected value."""

    ADMITTED = "admitted"
    NO_BINDING = "no_binding"
    OPTIONAL_ABSENT = "optional_absent"
    DIGEST_MISMATCH = "digest_mismatch"
    POLICY_UNAVAILABLE = "policy_unavailable"
    EGRESS_INCOMPATIBLE = "egress_incompatible"
    REQUIRED_CAPABILITY_UNAVAILABLE = "required_capability_unavailable"
    EMPTY_INTERSECTION = "empty_intersection"
    CURRENCY_MISMATCH = "currency_mismatch"
    SHARING_CONFLICT = "sharing_conflict"
    AUTHORITY_UNAVAILABLE = "authority_unavailable"
    STRATEGY_NOT_ALLOWED = "strategy_not_allowed"


class EventModelDemand(ClosedModel):
    """Organizer-authored typed model demand for one workload role (CTF-908).

    Constrained by the scenario need and the deployment/event envelope. It never
    names a provider, account, project, region, credential, endpoint, shard, or
    price — those stay deployment-owned in the catalog.
    """

    workload_role: Identifier
    expected_concurrency: PositiveInt
    per_participant_requests: PositiveInt
    per_participant_input_tokens: PositiveInt
    per_participant_output_tokens: PositiveInt
    allowed_strategy: AllocationStrategy


class ScenarioNeedProjection(ClosedModel):
    """A workload's authored scenario need plus its digest-verification status.

    ``need`` is ``None`` only when no binding is authored for the workload.
    ``digest_verified`` is whether the registered pack's current digest matches
    the digest the need was authored against; a required need over unverified
    content fails closed.
    """

    workload_role: Identifier
    need: ScenarioNeed | None
    digest_verified: StrictBool


class ModelAdmissionResult(ClosedModel):
    """Bounded, secret-free required-model admission decision for one workload."""

    workload_role: Identifier
    outcome: ModelAdmissionOutcome
    reason: ModelAdmissionReason
    required: StrictBool


_CONTRACT_ERROR_REASONS = {
    "policy.required_capability_unavailable": ModelAdmissionReason.REQUIRED_CAPABILITY_UNAVAILABLE,
    "policy.empty_intersection": ModelAdmissionReason.EMPTY_INTERSECTION,
    "policy.currency_mismatch": ModelAdmissionReason.CURRENCY_MISMATCH,
    "policy.profile_mismatch": ModelAdmissionReason.POLICY_UNAVAILABLE,
}


def decide_model_admission(
    *,
    projection: ScenarioNeedProjection,
    demand: EventModelDemand | None,
    profile: ModelProfile | None,
    sharing_admissible: bool | None,
    egress_permits_model: bool,
    authority_available: bool,
    sharing_profile: EffectiveProfile | None = None,
) -> ModelAdmissionResult:
    """Decide required-model admission for one workload, failing closed.

    ``sharing_admissible`` is the folded verdict of the sharing overlap compiler:
    ``None`` when no sharing binding applies, ``True``/``False`` otherwise.
    ``sharing_profile`` is the compiled effective profile of an admissible sharing
    overlap (when it carries a profile facet); the need is intersected against it
    so a sharing restriction actually tightens the decision.
    """
    need = projection.need
    if need is None:
        # No authored binding: this workload carries no required-model gate.
        return _result(
            projection.workload_role, ModelAdmissionOutcome.ADMITTED, ModelAdmissionReason.NO_BINDING, required=False
        )

    reason = _precondition_reason(projection.digest_verified, authority_available, profile, egress_permits_model)
    if reason is None:
        reason = _policy_reason(need, demand, profile, sharing_admissible, sharing_profile)
    return _render(projection.workload_role, bool(need.required), reason)


def _render(role: str, required: bool, reason: ModelAdmissionReason) -> ModelAdmissionResult:
    """Map a computed reason to the fail-closed outcome for one workload.

    A required need denies (or is indeterminate when the authority could not be
    consulted); an optional need renders as explicit visible absence and never
    blocks.
    """
    if reason is ModelAdmissionReason.ADMITTED:
        return _result(role, ModelAdmissionOutcome.ADMITTED, reason, required=required)
    if not required:
        return _absent(role)
    outcome = (
        ModelAdmissionOutcome.INDETERMINATE
        if reason is ModelAdmissionReason.AUTHORITY_UNAVAILABLE
        else ModelAdmissionOutcome.DENIED
    )
    return _result(role, outcome, reason, required=True)


def _precondition_reason(
    digest_verified: bool, authority_available: bool, profile: ModelProfile | None, egress_permits_model: bool
) -> ModelAdmissionReason | None:
    """Return the first failing precondition reason, or None when all hold.

    A binding authored against different pack content cannot be trusted; required
    access needs a live authority and an offered deployment profile; zero-egress
    is incompatible with required external model use.
    """
    checks = (
        (not digest_verified, ModelAdmissionReason.DIGEST_MISMATCH),
        (not authority_available, ModelAdmissionReason.AUTHORITY_UNAVAILABLE),
        (profile is None, ModelAdmissionReason.POLICY_UNAVAILABLE),
        (not egress_permits_model, ModelAdmissionReason.EGRESS_INCOMPATIBLE),
    )
    for failed, reason in checks:
        if failed:
            return reason
    return None


def _policy_reason(
    need: ScenarioNeed,
    demand: EventModelDemand | None,
    profile: ModelProfile | None,
    sharing_admissible: bool | None,
    sharing_profile: EffectiveProfile | None,
) -> ModelAdmissionReason:
    """Intersect the need with the deployment profile, then fold sharing effects."""
    if profile is None:
        return ModelAdmissionReason.POLICY_UNAVAILABLE
    try:
        effective = intersect_profile(profile, need)
    except ContractError as exc:
        return _CONTRACT_ERROR_REASONS.get(exc.code, ModelAdmissionReason.POLICY_UNAVAILABLE)
    return _effective_reason(need, demand, effective, sharing_admissible, sharing_profile)


def _effective_reason(
    need: ScenarioNeed,
    demand: EventModelDemand | None,
    effective: EffectiveProfile | None,
    sharing_admissible: bool | None,
    sharing_profile: EffectiveProfile | None,
) -> ModelAdmissionReason:
    """Fold the sharing overlap and organizer demand into the final reason.

    ``effective is None`` is an optional need with an empty catalog intersection:
    explicit visible unavailability.
    """
    if effective is None:
        return ModelAdmissionReason.OPTIONAL_ABSENT
    reason = ModelAdmissionReason.ADMITTED
    restricted = _restrict_by_sharing(effective, need, sharing_profile) if sharing_profile is not None else None
    if sharing_admissible is False:
        reason = ModelAdmissionReason.SHARING_CONFLICT
    elif restricted is not None:
        reason = restricted
    elif demand is not None and not _demand_strategy_allowed(demand, effective, sharing_profile):
        reason = ModelAdmissionReason.STRATEGY_NOT_ALLOWED
    return reason


def _demand_strategy_allowed(
    demand: EventModelDemand, effective: EffectiveProfile, sharing_profile: EffectiveProfile | None
) -> bool:
    """Whether the organizer's selected strategy stays within the effective envelope."""
    strategies = set(effective.allowed_strategies)
    if sharing_profile is not None:
        strategies &= set(sharing_profile.allowed_strategies)
    return demand.allowed_strategy in strategies


def _restrict_by_sharing(
    effective: EffectiveProfile,
    need: ScenarioNeed,
    sharing_profile: EffectiveProfile,
) -> ModelAdmissionReason | None:
    """Return a denial reason when the sharing overlap forecloses the need, else None.

    The sharing overlap must reference the same profile and must still leave every
    required capability available and a non-empty capability/region/strategy
    intersection once combined with the catalog-intersected envelope. An empty
    capability intersection is never admissible, even when the need lists no
    *required* capabilities (a subset check trivially passes for an empty set).
    """
    capabilities = set(effective.capabilities) & set(sharing_profile.capabilities)
    regions = set(effective.data_regions) & set(sharing_profile.data_regions)
    strategies = set(effective.allowed_strategies) & set(sharing_profile.allowed_strategies)
    reason: ModelAdmissionReason | None = None
    if sharing_profile.profile_id != need.profile_id:
        reason = ModelAdmissionReason.SHARING_CONFLICT
    elif not capabilities or not regions or not strategies:
        reason = ModelAdmissionReason.EMPTY_INTERSECTION
    elif not set(need.required_capabilities).issubset(capabilities):
        reason = ModelAdmissionReason.REQUIRED_CAPABILITY_UNAVAILABLE
    return reason


def _result(
    role: str, outcome: ModelAdmissionOutcome, reason: ModelAdmissionReason, *, required: bool
) -> ModelAdmissionResult:
    """Build one admission result."""
    return ModelAdmissionResult(workload_role=role, outcome=outcome, reason=reason, required=required)


def _absent(role: str) -> ModelAdmissionResult:
    """Optional access is absent as an explicit, non-blocking admitted outcome."""
    return _result(role, ModelAdmissionOutcome.ADMITTED, ModelAdmissionReason.OPTIONAL_ABSENT, required=False)


__all__ = [
    "EventModelDemand",
    "ModelAdmissionOutcome",
    "ModelAdmissionReason",
    "ModelAdmissionResult",
    "ScenarioNeedProjection",
    "decide_model_admission",
]
