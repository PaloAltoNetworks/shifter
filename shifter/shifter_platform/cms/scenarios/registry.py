"""RAES package-source scenario registry with metadata access overlays."""

from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import RaesPackageSource
    from shared.schemas.cms_projections import ScenarioProjection

logger = logging.getLogger(__name__)


class ScenarioWorkflow(enum.StrEnum):
    """Workflow purpose a scenario listing / launchability check is scoped to.

    ``STAFF_REVIEW`` is the unfiltered catalog view (staff may see
    non-launchable RAES entries for review). Every other value is a launch
    purpose whose selection must be restricted to launchable entries.
    """

    STAFF_REVIEW = "staff_review"
    RANGE_LAUNCH = "range_launch"
    CTF_EVENT = "ctf_event"
    CTF_PARTICIPANT = "ctf_participant"
    EXPERIMENT = "experiment"


# Data-driven launchability allowlists. Widen these constants (not the call
# sites) when a new supported RAES source / contract / profile lands. Both
# ``repo`` and ``object`` are launchable (object via the #1567 launch resolver,
# ADR-034-R5); object launchability also requires a configured package bucket
# (see :func:`_source_kind_launchable`), so an object-backed row with none set
# stays registrable and visible but non-launchable (fail closed).
LAUNCHABLE_SOURCE_KINDS = frozenset({"repo", "object"})
LAUNCHABLE_CONTRACT_KINDS = frozenset({"raes"})
LAUNCHABLE_CONTRACT_PROFILES = frozenset({"shifter"})

# Resolved at launch by the #1567 object resolver, not under RAES_PACKAGE_ROOT.
_OBJECT_SOURCE_KIND = "object"

# (contract_kind, contract_profile) pairs that have a wired runtime launch
# adapter — i.e. a launchable entry of that kind/profile can actually be turned
# into a Shifter range by the RAES launch path (#1479:
# cms.services.create_raes_native_range -> shared.raes package loader -> engine
# dispatch).
_LAUNCH_ADAPTER_CONTRACT_PROFILES: frozenset[tuple[str, str]] = frozenset({("raes", "shifter")})


def _get_metadata_map() -> dict[str, dict[str, Any]]:
    """Load all ScenarioMetadata rows as a dict keyed by scenario_id.

    Returns:
        {scenario_id: {"enabled": bool, "staff_only": bool}, ...}
    """
    from cms.models import ScenarioMetadata

    return {m.scenario_id: {"enabled": m.enabled, "staff_only": m.staff_only} for m in ScenarioMetadata.objects.all()}


def _get_raes_sources() -> list[RaesPackageSource]:
    """Load all RAES package-source rows for the catalog projection.

    Returns:
        List of RaesPackageSource instances.
    """
    from cms.models import RaesPackageSource

    return list(RaesPackageSource.objects.all())


def _raes_source_refs_valid(source: RaesPackageSource) -> bool:
    """Re-validate an RAES row's refs/digests/provenance against the shared contract."""
    from shared.schemas.raes_package_source import (
        PackageSourceRecord,
        RaesPackageSourceError,
        validate_package_source,
    )

    try:
        validate_package_source(
            PackageSourceRecord(
                source_kind=source.source_kind,
                contract_kind=source.contract_kind,
                contract_profile=source.contract_profile,
                package_ref=source.package_ref,
                package_version=source.package_version,
                package_digest=source.package_digest,
                conformance_status=source.conformance_status,
                lock_ref=source.lock_ref,
                lock_digest=source.lock_digest,
                conformance_report_ref=source.conformance_report_ref,
                provenance=source.provenance,
            )
        )
    except RaesPackageSourceError:
        return False
    return True


def _raes_launchable(source: RaesPackageSource) -> bool:
    """Data-driven launchability decision for an RAES package-source row.

    Launchability is NOT merely ``conformance_status == "passed"``. An RAES
    entry is launchable only when ALL hold (fail-closed):

    - a runtime hydration adapter exists for its contract/profile;
    - its source kind, contract kind, and contract profile are supported;
    - its conformance status is ``passed``;
    - its refs/digests/provenance re-validate against the shared contract.

    Args:
        source: RaesPackageSource instance.
    Returns:
        True only if the entry is launchable.
    """
    from cms.models import RaesPackageSource as _RaesPackageSource

    return (
        # Never launchable until a runtime adapter exists for this contract/profile.
        (source.contract_kind, source.contract_profile) in _LAUNCH_ADAPTER_CONTRACT_PROFILES
        and source.contract_kind in LAUNCHABLE_CONTRACT_KINDS
        and source.contract_profile in LAUNCHABLE_CONTRACT_PROFILES
        and _source_kind_launchable(source.source_kind)
        and source.conformance_status == _RaesPackageSource.ConformanceStatus.PASSED
        and _raes_source_refs_valid(source)
    )


def _source_kind_launchable(source_kind: str) -> bool:
    """Whether a source kind is launchable; ``object`` also requires a configured
    package bucket (config readiness, not a catalog-time network probe)."""
    if source_kind not in LAUNCHABLE_SOURCE_KINDS:
        return False
    if source_kind == _OBJECT_SOURCE_KIND:
        return bool(str(getattr(settings, "RAES_PACKAGE_BUCKET", "") or "").strip())
    return True


def _raes_source_to_dict(
    source: RaesPackageSource,
    *,
    metadata: dict[str, Any] | None,
    launchable: bool,
) -> ScenarioProjection:
    """Build a catalog projection entry for an RAES package-source row.

    RAES rows are provenance-only, so display fields are derived (name from
    scenario_id, empty description). Access comes from the shared
    ``ScenarioMetadata`` overlay; ``launchable`` is the data-driven registry
    decision (see :func:`_raes_launchable`), independent of access.

    Args:
        source: RaesPackageSource instance.
        metadata: Override dict with enabled/staff_only, or None for defaults.
        launchable: The computed launchability decision for this entry.

    Returns:
        Projection dict containing catalog metadata (id/name/enabled/
        staff_only/is_default/launchable/agent_requirements) plus RAES source fields.
    """
    if metadata is not None:
        enabled = metadata["enabled"]
        staff_only = metadata.get("staff_only", False)
    else:
        enabled = True
        staff_only = False

    return {
        "id": source.scenario_id,
        "name": source.scenario_id,
        "description": "",
        "scenario_type": "raes",
        "source_kind": source.source_kind,
        "contract_kind": source.contract_kind,
        "contract_profile": source.contract_profile,
        "is_default": False,
        "enabled": enabled,
        "staff_only": staff_only,
        "launchable": launchable,
        "agent_requirements": {
            "requires_windows": False,
            "requires_linux": False,
            "has_from_agent": False,
        },
    }


def list_all_scenarios(user: User | None = None) -> list[ScenarioProjection]:
    """Get all RAES package sources with metadata access overlays applied.

    Args:
        user: Requesting user. If None, returns all (no access filtering).
              If user is not staff, staff_only scenarios are excluded.
              Only enabled scenarios are returned for non-staff users.

    Returns:
        List of scenario dicts sorted by name.
    """
    metadata_map = _get_metadata_map()

    result = _raes_source_entries(metadata_map)

    if user is not None and not (user.is_staff or user.is_superuser):
        result = [s for s in result if s["enabled"] and not s["staff_only"]]
    result.sort(key=lambda s: s["name"])
    return result


def _raes_source_entries(metadata_map: dict[str, Any]) -> list[ScenarioProjection]:
    """Build the authoritative RAES catalog entries."""
    entries = []
    for source in _get_raes_sources():
        launchable = _raes_launchable(source)
        entries.append(
            _raes_source_to_dict(source, metadata=metadata_map.get(source.scenario_id), launchable=launchable)
        )
    return entries


def get_catalog_entry(scenario_id: str) -> ScenarioProjection | None:
    """Return the unified projection entry for a scenario id, or None if absent.

    Uses the unfiltered projection (no access filtering) so callers can inspect
    launchability regardless of the requesting user.
    """
    for entry in list_all_scenarios(user=None):
        if entry["id"] == scenario_id:
            return entry
    return None


def list_launchable_scenarios(
    user: User | None = None,
    workflow: ScenarioWorkflow = ScenarioWorkflow.RANGE_LAUNCH,
) -> list[ScenarioProjection]:
    """List scenarios a given workflow may launch.

    ``STAFF_REVIEW`` returns the full access-filtered projection (including
    non-launchable RAES entries for review). Every launch workflow returns only
    entries whose ``launchable`` flag is set.
    """
    scenarios = list_all_scenarios(user=user)
    if workflow == ScenarioWorkflow.STAFF_REVIEW:
        return scenarios
    return [s for s in scenarios if s.get("launchable", True)]


def is_scenario_launchable(
    scenario_id: str,
    workflow: ScenarioWorkflow = ScenarioWorkflow.RANGE_LAUNCH,
) -> bool:
    """Whether a scenario id is launchable for the given workflow.

    Unknown ids return False (callers that must distinguish "unknown" from
    "known but not launchable" should use :func:`get_catalog_entry`).
    """
    entry = get_catalog_entry(scenario_id)
    if entry is None:
        return False
    if workflow == ScenarioWorkflow.STAFF_REVIEW:
        return True
    return bool(entry.get("launchable", True))


def get_scenario_detail(scenario_id: str) -> ScenarioProjection:
    """Get a single RAES package-source scenario by ID.

    Args:
        scenario_id: Unique scenario identifier.

    Returns:
        Scenario dict with metadata overlay.

    Raises:
        ValueError: If scenario not found in either source.
    """
    detail = get_catalog_entry(scenario_id)
    if detail is None:
        raise ValueError(f"Scenario '{scenario_id}' not found")
    return detail


def check_scenario_access(scenario_id: str, user: User) -> ScenarioProjection:
    """Check if a user can access a scenario. Returns detail dict or raises ValueError.

    Staff and superusers can access all scenarios. Non-staff users are blocked
    from disabled or staff_only scenarios.

    Args:
        scenario_id: Unique scenario identifier.
        user: The requesting user.

    Returns:
        Scenario detail dict (from get_scenario_detail).

    Raises:
        ValueError: If scenario not found or user lacks access.
    """
    detail = get_scenario_detail(scenario_id)
    if not (user.is_staff or user.is_superuser) and (not detail["enabled"] or detail["staff_only"]):
        raise ValueError(f"Scenario '{scenario_id}' is not available")
    return detail
