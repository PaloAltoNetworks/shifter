"""CMS launch-boundary required-model admission gate (PLAT-202, #2119).

Every range launch — cold participant/spare/wave/standalone/recovery-rebuild and
warm-claim activation — funnels through ``_create_raes_native_range_impl``. This
gate runs there, before any dispatch, so required model access is enforced
uniformly across every launch family. It is deliberately distinct from the
best-effort PLAT-201 capacity path: a required-model denial or indeterminate
outcome fails the launch closed instead of proceeding.

CMS owns scenario hydration and egress posture (it resolves the scenario need
projection and maps the egress mode); the Engine owns the authoritative
fail-closed decision, folding deployment policy and the #2139/#2140 sharing
overlap. A scenario with no authored need — or only optional needs that resolve
to visible absence — passes through unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime

from cms.exceptions import CMSError
from shared.log_sanitize import safe_log_value
from shared.model_access import ModelAdmissionOutcome, OwnedReference

logger = logging.getLogger(__name__)

# Zero-egress postures cannot carry required external model use without an
# admitted private-broker capability (a later milestone). See #2119.
_ZERO_EGRESS_MODES = frozenset({"deny-all", "none"})
_DENIED_MESSAGE = "Required model access could not be admitted for this launch."


def _subject_for_user(user: object) -> OwnedReference:
    """The launcher's canonical sharing subject reference (matches CMS sharing)."""
    return OwnedReference(owner="management", reference=f"user:{getattr(user, 'id', 0)}")


def assert_launch_model_access(
    *,
    user: object,
    scenario_id: str,
    egress_mode: str,
    subject: OwnedReference | None = None,
    package_digest: str | None = None,
    now: datetime | None = None,
) -> None:
    """Enforce required-model admission before a launch dispatches; fail closed.

    ``subject`` is the canonical membership identity the sharing overlap resolves
    against (a CTF draw reference for a participant awaiting provisioning). When a
    caller has no draw/range membership identity yet (a brand-new spare, or a
    non-CTF launch), it is omitted; no range-scoped sharing binding can apply to a
    range that does not exist, so the launcher reference is used and simply matches
    no membership. It is never used to stand in for a real draw subject.

    Raises :class:`cms.exceptions.CMSError` with a bounded, secret-free reason
    when any required need is denied or indeterminate. Returns ``None`` when the
    scenario has no authored required-model need.
    """
    from cms.scenarios.model_needs import project_scenario_model_needs
    from engine.services import admit_range_model_access

    projection = project_scenario_model_needs(scenario_id, expected_digest=package_digest)
    if projection.resolution_failed:
        # The overlay could not be resolved (read error or malformed stored
        # need). This is not a confirmed absence, so fail the launch closed
        # rather than proceed as if no need existed.
        logger.warning("model-access: launch refused for scenario %s (needs unresolvable)", safe_log_value(scenario_id))
        raise CMSError(_DENIED_MESSAGE, details={"code": "model-access-denied", "reason_codes": ["needs_unavailable"]})
    # No authored model need: no required-model gate.
    if not projection.needs:
        return

    from django.conf import settings

    from shared.model_access import ContractError
    from shared.model_access.projection_port import refresh_launch_projections

    catalog = getattr(settings, "MODEL_ACCESS_CATALOG", None)
    if getattr(settings, "MODEL_ACCESS_ENABLED", False) and catalog is not None:
        try:
            refresh_launch_projections(catalog.deployment_id)
        except ContractError:
            raise CMSError(
                _DENIED_MESSAGE, details={"code": "model-access-denied", "reason_codes": ["authority_unavailable"]}
            ) from None

    need_projections = {role: projection.for_workload(role) for role in projection.needs}
    egress_permits_model = egress_mode not in _ZERO_EGRESS_MODES
    results = admit_range_model_access(
        subject=subject if subject is not None else _subject_for_user(user),
        need_projections=need_projections,
        demands={},
        egress_permits_model=egress_permits_model,
        now=now,
    )
    refused = [result for result in results if result.outcome is not ModelAdmissionOutcome.ADMITTED]
    if refused:
        reason_codes = sorted({result.reason.value for result in refused})
        logger.warning(
            "model-access: launch refused for scenario %s reasons=%s",
            safe_log_value(scenario_id),
            safe_log_value(",".join(reason_codes)),
        )
        raise CMSError(_DENIED_MESSAGE, details={"code": "model-access-denied", "reason_codes": reason_codes})
