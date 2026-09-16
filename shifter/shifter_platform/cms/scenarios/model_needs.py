"""Per-pack scenario→model-need overlay: validation and projection (PLAT-202, #2119).

The overlay (:class:`cms.models.ScenarioModelNeeds`) is Shifter-owned,
staff-authored, digest-bound metadata that rides the runtime pack lifecycle. It
is intentionally separate from the deploy-time mounted model-access catalog (which
owns deployment policy the need references) and from the provenance-only
``RaesPackageSource``. This module validates the stored binding and projects it
for admission, mirroring :mod:`cms.scenarios.images`: it never raises, and an
unresolvable binding degrades to "no need" rather than a fabricated grant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from shared.model_access import ScenarioNeed, ScenarioNeedProjection
from shared.model_access.catalog import ContractError

logger = logging.getLogger(__name__)


def validate_scenario_model_needs(authored_package_digest: str, needs: object) -> dict[str, dict[str, object]]:
    """Validate the ``{workload_role: ScenarioNeed}`` overlay payload.

    Returns the normalized JSON-safe mapping to persist. Each entry must parse as
    a :class:`~shared.model_access.ScenarioNeed` whose ``workload_role`` equals its
    key and whose ``scenario_digest`` equals the authored package digest. A
    malformed binding must never persist, so this fails closed with a bounded
    :class:`~shared.model_access.catalog.ContractError`.
    """
    if not isinstance(needs, dict) or not needs:
        raise ContractError("scenario_needs.empty", "needs")
    normalized: dict[str, dict[str, object]] = {}
    for role, payload in needs.items():
        try:
            need = ScenarioNeed.model_validate(payload)
        except ValidationError as exc:
            raise ContractError("scenario_needs.invalid", f"needs.{role}") from exc
        if need.workload_role != role:
            raise ContractError("scenario_needs.workload_role_mismatch", f"needs.{role}")
        if need.scenario_digest != authored_package_digest:
            raise ContractError("scenario_needs.digest_mismatch", f"needs.{role}")
        normalized[role] = need.model_dump(mode="json")
    return normalized


@dataclass(frozen=True)
class ScenarioModelNeedsProjection:
    """Resolved per-pack needs plus whether the pack's current digest matches.

    ``digest_verified`` is meaningful only for a workload whose need is present:
    it is True only when a registered pack exists and its current digest equals
    the digest the needs were authored against.

    ``resolution_failed`` distinguishes a *confirmed* absence of any authored need
    (an empty ``needs`` that the caller may treat as "no gate") from a *failure to
    resolve* one (a database error or a malformed stored payload). A resolution
    failure must never be read as absence: the caller fails the launch closed
    because it cannot prove whether a required need exists.
    """

    needs: dict[str, ScenarioNeed]
    digest_verified: bool
    resolution_failed: bool = False

    def for_workload(self, workload_role: str) -> ScenarioNeedProjection:
        """Project one workload's need into the shared admission-input DTO."""
        return ScenarioNeedProjection(
            workload_role=workload_role,
            need=self.needs.get(workload_role),
            digest_verified=self.digest_verified,
        )


def project_scenario_model_needs(
    scenario_id: str, *, expected_digest: str | None = None
) -> ScenarioModelNeedsProjection:
    """Resolve a scenario's authored model needs; never raises.

    An unknown scenario or missing overlay yields an empty projection, so a
    scenario with no authored need carries no required-model gate. When an overlay
    exists, ``digest_verified`` reflects whether the pack digest matches the
    authored digest so a re-registered pack fails closed rather than inheriting
    stale needs.

    ``expected_digest`` is the digest of the exact package snapshot being launched.
    When supplied, the overlay is verified against *that* digest rather than an
    independent re-read of the registration, so a registration replaced between
    snapshot capture and admission cannot let admission verify one package while
    dispatch launches another. When omitted, the current registration digest is
    used.
    """
    from cms.models import RaesPackageSource, ScenarioModelNeeds

    needs: dict[str, ScenarioNeed] = {}
    try:
        row = ScenarioModelNeeds.objects.filter(scenario_id=scenario_id).first()
        for role, payload in (row.needs if row is not None else {}).items():
            needs[role] = ScenarioNeed.model_validate(payload)
    except Exception:
        # A read failure or a malformed stored need is a *resolution failure*, not
        # a confirmed absence: fail closed rather than letting the launch gate
        # treat an unreadable/untrusted overlay as "no need".
        logger.exception("model-access: could not resolve scenario model needs")
        return ScenarioModelNeedsProjection(needs={}, digest_verified=False, resolution_failed=True)
    if row is None:
        return ScenarioModelNeedsProjection(needs={}, digest_verified=False)

    if expected_digest is not None:
        current_digest = expected_digest
    else:
        source = RaesPackageSource.objects.filter(scenario_id=scenario_id).first()
        current_digest = source.package_digest if source is not None else ""
    digest_verified = bool(current_digest) and current_digest == row.authored_package_digest
    return ScenarioModelNeedsProjection(needs=needs, digest_verified=digest_verified)
