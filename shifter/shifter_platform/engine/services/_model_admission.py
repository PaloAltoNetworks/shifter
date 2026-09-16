"""Engine-owned required-model admission decision (PLAT-202, #2119).

This is the authoritative admission seam ADR-060 requires: required model access
must succeed through an enforcing decision that fails closed, independent of the
best-effort PLAT-201 capacity helpers and of whether general compute planning is
enabled. It composes the trusted per-workload scenario-need projection (resolved
by CMS, which owns scenario hydration) with the deployment catalog profile and
the sharing overlap resolution, then delegates the fail-closed verdict to the
pure :func:`shared.model_access.decide_model_admission`.

The admit/deny verdict is a deterministic function of (need, catalog profile,
sharing overlap, egress posture, authority availability), so a launch retry
recomputes the same outcome without a persisted decision. Immutable allocation
and request accounting (which do need persistence) are a later milestone and out
of scope here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime

from shared.model_access import (
    EffectivePolicy,
    EffectiveProfile,
    EventModelDemand,
    ModelAccessCatalog,
    ModelAdmissionResult,
    ModelProfile,
    OwnedReference,
    ScenarioNeedProjection,
    decide_model_admission,
)

logger = logging.getLogger(__name__)


def admit_range_model_access(
    *,
    subject: OwnedReference | dict,
    need_projections: Mapping[str, ScenarioNeedProjection],
    demands: Mapping[str, EventModelDemand],
    egress_permits_model: bool,
    catalog: ModelAccessCatalog | None = None,
    now: datetime | None = None,
) -> tuple[ModelAdmissionResult, ...]:
    """Decide required-model admission for every demanded/needed workload.

    ``need_projections`` is the CMS-resolved, digest-verified projection per
    workload role; ``demands`` is the organizer's typed model demand per role.
    Returns one bounded, secret-free :class:`ModelAdmissionResult` per role, with
    every required denial or indeterminate outcome preserved for the caller to
    refuse the launch before dispatch.
    """
    resolved_catalog = _effective_catalog(catalog)
    sharing_admissible, authority_available, sharing_profile = _resolve_sharing(resolved_catalog, subject, now)

    roles = sorted(set(need_projections) | set(demands))
    results: list[ModelAdmissionResult] = []
    for role in roles:
        projection = need_projections.get(role) or _absent_projection(role)
        profile = _profile_for(resolved_catalog, projection)
        results.append(
            decide_model_admission(
                projection=projection,
                demand=demands.get(role),
                profile=profile,
                sharing_admissible=sharing_admissible,
                sharing_profile=sharing_profile,
                egress_permits_model=egress_permits_model,
                authority_available=authority_available,
            )
        )
    return tuple(results)


def _effective_catalog(catalog: ModelAccessCatalog | None) -> ModelAccessCatalog | None:
    """Resolve the catalog only when model access is actually enabled.

    A validated catalog can be mounted even while the deployment has model access
    disabled (runtime `MODEL_ACCESS_ENABLED` false, or the catalog's own `enabled`
    flag false). A disabled deployment must not admit required access, so treat a
    disabled catalog as absent — required needs then deny as `policy_unavailable`,
    optional needs remain visible absence.
    """
    resolved = catalog if catalog is not None else _configured_catalog()
    if resolved is not None and not resolved.enabled:
        return None
    return resolved


def _configured_catalog() -> ModelAccessCatalog | None:
    """Return the mounted deployment catalog, or None when model access is unconfigured/disabled."""
    from django.conf import settings

    if not getattr(settings, "MODEL_ACCESS_ENABLED", False):
        return None
    return getattr(settings, "MODEL_ACCESS_CATALOG", None)


def _absent_projection(role: str) -> ScenarioNeedProjection:
    """A workload with no authored need carries no required-model gate."""
    return ScenarioNeedProjection(workload_role=role, need=None, digest_verified=False)


def _profile_for(catalog: ModelAccessCatalog | None, projection: ScenarioNeedProjection) -> ModelProfile | None:
    """Resolve the deployment profile the need references, or None when unavailable."""
    if catalog is None or projection.need is None:
        return None
    return next((profile for profile in catalog.profiles if profile.profile_id == projection.need.profile_id), None)


def _resolve_sharing(
    catalog: ModelAccessCatalog | None,
    subject: OwnedReference | dict,
    now: datetime | None,
) -> tuple[bool | None, bool, EffectiveProfile | None]:
    """Fold the subject's sharing overlap into (admissible, authority_available, profile).

    Reuses the existing effective-policy compiler (#2139/#2140). No matching
    binding yields ``(None, True, None)`` — no sharing constraint. A
    stale/unresolvable membership projection fails closed as an unavailable
    authority (``authority_available=False``); a real overlap conflict yields
    ``sharing_admissible=False``. When the overlap is admissible its compiled
    ``effective_profile`` is returned so admission intersects the scenario need
    against the full effective envelope, not just the catalog profile.
    """
    if catalog is None:
        return None, True, None
    try:
        from engine.services._sharing import preview_effective_policy

        effective = preview_effective_policy(
            deployment_id=catalog.deployment_id,
            catalog=catalog,
            subject=subject,
            now=now,
        )
    except Exception:
        # The authority could not be consulted: required access is indeterminate.
        logger.exception("model-access: sharing authority unavailable during admission")
        return None, False, None
    return _fold_sharing(effective)


def _fold_sharing(effective: EffectivePolicy) -> tuple[bool | None, bool, EffectiveProfile | None]:
    """Fold a compiled effective policy into (admissible, authority_available, profile).

    No matching binding is no constraint; a stale membership projection fails
    closed as an unavailable authority; otherwise the overlap's admissibility and
    compiled profile carry forward.
    """
    if not effective.contributions:
        return None, True, None
    if effective.stale:
        return None, False, None
    return effective.admissible, True, effective.effective_profile
