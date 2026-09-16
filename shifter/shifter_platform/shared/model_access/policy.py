"""Fail-closed profile intersection for scenario and deployment policy."""

from __future__ import annotations

from shared.model_access.catalog import ContractError
from shared.model_access.core_models import AccessLimits, EffectiveProfile, ModelProfile, ScenarioNeed


def intersect_profile(profile: ModelProfile, need: ScenarioNeed) -> EffectiveProfile | None:
    """Operation for intersect profile."""
    if profile.profile_id != need.profile_id:
        raise ContractError("policy.profile_mismatch", "profile_id")
    available = set(profile.capabilities) & set(need.allowed_capabilities)
    missing = set(need.required_capabilities) - available
    strategies = tuple(item for item in profile.allowed_strategies if item in need.allowed_strategies)
    regions = tuple(item for item in profile.data_regions if item in need.data_regions)
    result = None
    if missing:
        _unavailable(need, "policy.required_capability_unavailable", "required_capabilities")
    elif not available or not strategies or not regions:
        _unavailable(need, "policy.empty_intersection")
    else:
        limits = _tightened_limits(profile, need)
        if limits is not None:
            result = EffectiveProfile(
                profile_id=profile.profile_id,
                required=need.required,
                capabilities=tuple(item for item in profile.capabilities if item in available),
                allowed_strategies=strategies,
                data_regions=regions,
                limits=limits,
            )
    return result


def _unavailable(need: ScenarioNeed, code: str, path: str = "<root>") -> None:
    """Operation for unavailable."""
    if need.required:
        raise ContractError(code, path)


def _tightened_limits(profile: ModelProfile, need: ScenarioNeed) -> AccessLimits | None:
    """Tighten limits while preserving optional-feature semantics."""
    limits = None
    try:
        limits = profile.limits.tightened_with(need.limits)
    except ValueError as exc:
        if need.required:
            raise ContractError("policy.currency_mismatch", "limits.currency") from exc
    return limits
