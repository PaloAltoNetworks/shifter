"""Scenario registry - unified access to YAML defaults and DB customs.

Merges scenario templates from two sources:
1. YAML files in cms/scenarios/templates/ (defaults, code-managed)
2. Scenario model instances in the database (staff-created customs)

Applies ScenarioMetadata overlays (enabled, staff_only) to all scenarios.
"""

from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING, Any

from cms.scenarios.loader import get_all_scenarios as get_yaml_scenarios
from cms.scenarios.loader import list_scenario_ids as list_yaml_ids
from cms.scenarios.loader import load_scenario as load_yaml_scenario
from cms.scenarios.schema import AnyScenarioTemplate, CTFScenarioTemplate, ScenarioTemplate
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import AcesPackageSource

logger = logging.getLogger(__name__)


class ScenarioWorkflow(enum.StrEnum):
    """Workflow purpose a scenario listing / launchability check is scoped to.

    ``STAFF_REVIEW`` is the unfiltered catalog view (staff may see
    non-launchable ACES entries for review). Every other value is a launch
    purpose whose selection must be restricted to launchable entries.
    """

    STAFF_REVIEW = "staff_review"
    RANGE_LAUNCH = "range_launch"
    CTF_EVENT = "ctf_event"
    CTF_PARTICIPANT = "ctf_participant"
    EXPERIMENT = "experiment"


# Data-driven launchability allowlists. Widen these constants (not the call
# sites) when a new supported ACES source / contract / profile lands.
LAUNCHABLE_SOURCE_KINDS = frozenset({"repo", "object"})
LAUNCHABLE_CONTRACT_KINDS = frozenset({"aces"})
LAUNCHABLE_CONTRACT_PROFILES = frozenset({"shifter"})

# (contract_kind, contract_profile) pairs that have a wired runtime hydration
# adapter — i.e. a launchable entry of that kind/profile can actually be turned
# into a Shifter range/CTF spec by the launch path. This is EMPTY until an ACES
# hydrator/adapter lands (a later issue), so ACES entries stay review-only and
# are never marked launchable, even when conformant. Marking an entry launchable
# before the adapter exists would expose an id that fails late at hydration.
_LAUNCH_ADAPTER_CONTRACT_PROFILES: frozenset[tuple[str, str]] = frozenset()


def _get_metadata_map() -> dict[str, dict[str, Any]]:
    """Load all ScenarioMetadata rows as a dict keyed by scenario_id.

    Returns:
        {scenario_id: {"enabled": bool, "staff_only": bool}, ...}
    """
    from cms.models import ScenarioMetadata

    return {m.scenario_id: {"enabled": m.enabled, "staff_only": m.staff_only} for m in ScenarioMetadata.objects.all()}


def _get_db_scenarios() -> list[AnyScenarioTemplate]:
    """Load all active (non-deleted) custom scenarios from the database.

    Returns:
        List of ScenarioTemplate objects built from Scenario model instances.
    """
    from cms.models import Scenario

    scenarios = []
    for s in Scenario.objects.all():
        try:
            scenarios.append(s.to_template())
        except Exception:
            logger.warning(
                "Skipping invalid DB scenario: scenario_id=%s, id=%s",
                safe_log_value(s.scenario_id),
                s.id,
            )
    return scenarios


def _get_aces_sources() -> list[AcesPackageSource]:
    """Load all ACES package-source rows for the catalog projection.

    Returns:
        List of AcesPackageSource instances.
    """
    from cms.models import AcesPackageSource

    return list(AcesPackageSource.objects.all())


def _aces_source_refs_valid(source: AcesPackageSource) -> bool:
    """Re-validate an ACES row's refs/digests/provenance against the shared contract."""
    from shared.schemas.aces_package_source import (
        AcesPackageSourceError,
        PackageSourceRecord,
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
    except AcesPackageSourceError:
        return False
    return True


def _aces_launchable(source: AcesPackageSource, *, known_legacy_ids: set[str]) -> bool:
    """Data-driven launchability decision for an ACES package-source row.

    Launchability is NOT merely ``conformance_status == "passed"``. An ACES
    entry is launchable only when ALL hold (fail-closed):

    - a runtime hydration adapter exists for its contract/profile;
    - it does not shadow an active legacy ``scenario_id``;
    - its source kind, contract kind, and contract profile are supported;
    - its conformance status is ``passed``;
    - its refs/digests/provenance re-validate against the shared contract.

    Args:
        source: AcesPackageSource instance.
        known_legacy_ids: Active YAML-default + DB-custom ids (no-shadow set).

    Returns:
        True only if the entry is launchable.
    """
    from cms.models import AcesPackageSource as _AcesPackageSource

    return (
        # Never launchable until a runtime adapter exists for this contract/profile.
        (source.contract_kind, source.contract_profile) in _LAUNCH_ADAPTER_CONTRACT_PROFILES
        and source.scenario_id not in known_legacy_ids
        and source.contract_kind in LAUNCHABLE_CONTRACT_KINDS
        and source.contract_profile in LAUNCHABLE_CONTRACT_PROFILES
        and source.source_kind in LAUNCHABLE_SOURCE_KINDS
        and source.conformance_status == _AcesPackageSource.ConformanceStatus.PASSED
        and _aces_source_refs_valid(source)
    )


def _aces_source_to_dict(
    source: AcesPackageSource,
    *,
    metadata: dict[str, Any] | None,
    launchable: bool,
) -> dict[str, Any]:
    """Build a catalog projection entry for an ACES package-source row.

    ACES rows are provenance-only, so display fields are derived (name from
    scenario_id, empty description). Access comes from the shared
    ``ScenarioMetadata`` overlay; ``launchable`` is the data-driven registry
    decision (see :func:`_aces_launchable`), independent of access.

    Args:
        source: AcesPackageSource instance.
        metadata: Override dict with enabled/staff_only, or None for defaults.
        launchable: The computed launchability decision for this entry.

    Returns:
        Projection dict shaped like other catalog entries (id/name/enabled/
        staff_only/is_default/launchable/agent_requirements) plus ACES source fields.
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
        "scenario_type": "aces",
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


def is_default_scenario(scenario_id: str) -> bool:
    """Check if a scenario_id corresponds to a YAML default.

    Args:
        scenario_id: The scenario identifier to check.

    Returns:
        True if the scenario exists as a YAML file in templates/.
    """
    return scenario_id in list_yaml_ids()


def _scenario_to_dict(
    template: AnyScenarioTemplate,
    *,
    is_default: bool,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Convert a ScenarioTemplate to a dict with metadata overlay.

    Args:
        template: Validated scenario template.
        is_default: Whether this is a YAML-based default.
        metadata: Override dict with enabled/staff_only, or None for defaults.

    Returns:
        Dict with scenario fields plus is_default, enabled, staff_only,
        and agent_requirements.
    """
    data = template.model_dump()

    # Apply metadata overlay (defaults: enabled=True, staff_only=False)
    if metadata is not None:
        data["enabled"] = metadata["enabled"]
        data["staff_only"] = metadata.get("staff_only", False)
    else:
        # No metadata row — use template's own enabled flag, default staff_only
        data["staff_only"] = False

    data["is_default"] = is_default
    # Legacy YAML defaults and DB custom scenarios have always been launchable;
    # expose it as an explicit, uniform flag so launch consumers can filter on it.
    data["launchable"] = True
    if isinstance(template, ScenarioTemplate):
        data["agent_requirements"] = template.get_agent_requirements()
    else:
        data["agent_requirements"] = {
            "requires_windows": False,
            "requires_linux": False,
            "has_from_agent": False,
        }
    return data


def list_all_scenarios(user: User | None = None) -> list[dict[str, Any]]:
    """Get all scenarios from both sources with metadata applied.

    Combines YAML defaults and DB customs, applies metadata overlays,
    and filters based on user role.

    Args:
        user: Requesting user. If None, returns all (no access filtering).
              If user is not staff, staff_only scenarios are excluded.
              Only enabled scenarios are returned for non-staff users.

    Returns:
        List of scenario dicts sorted by name.
    """
    metadata_map = _get_metadata_map()

    yaml_entries, yaml_ids = _yaml_source_entries(metadata_map)
    db_entries, db_ids = _db_source_entries(metadata_map, yaml_ids)
    aces_entries = _aces_source_entries(metadata_map, yaml_ids | db_ids)
    result = yaml_entries + db_entries + aces_entries

    # Access filtering
    if user is not None and not (user.is_staff or user.is_superuser):
        result = [s for s in result if s["enabled"] and not s["staff_only"]]

    # Sort by name
    result.sort(key=lambda s: s["name"])
    return result


def _yaml_source_entries(metadata_map: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    """Build projection entries for YAML defaults; return (entries, ids)."""
    entries = []
    yaml_ids = set()
    for template in get_yaml_scenarios():
        yaml_ids.add(template.id)
        entries.append(_scenario_to_dict(template, is_default=True, metadata=metadata_map.get(template.id)))
    return entries, yaml_ids


def _db_source_entries(metadata_map: dict[str, Any], yaml_ids: set[str]) -> tuple[list[dict[str, Any]], set[str]]:
    """Build entries for DB customs, skipping ids that collide with YAML defaults."""
    entries = []
    db_ids = set()
    for template in _get_db_scenarios():
        if template.id in yaml_ids:
            logger.warning("DB scenario '%s' collides with YAML default, skipping", template.id)
            continue
        db_ids.add(template.id)
        entries.append(_scenario_to_dict(template, is_default=False, metadata=metadata_map.get(template.id)))
    return entries, db_ids


def _aces_source_entries(metadata_map: dict[str, Any], known_ids: set[str]) -> list[dict[str, Any]]:
    """Build ACES entries, fail-closed skipping any id that shadows an active legacy scenario."""
    entries = []
    for source in _get_aces_sources():
        if source.scenario_id in known_ids:
            logger.warning(
                "ACES package-source '%s' collides with an active legacy scenario_id, skipping",
                safe_log_value(source.scenario_id),
            )
            continue
        launchable = _aces_launchable(source, known_legacy_ids=known_ids)
        entries.append(
            _aces_source_to_dict(source, metadata=metadata_map.get(source.scenario_id), launchable=launchable)
        )
    return entries


def get_catalog_entry(scenario_id: str) -> dict[str, Any] | None:
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
) -> list[dict[str, Any]]:
    """List scenarios a given workflow may launch.

    ``STAFF_REVIEW`` returns the full access-filtered projection (including
    non-launchable ACES entries for review). Every launch workflow returns only
    entries whose ``launchable`` flag is set. Legacy YAML/DB entries are always
    launchable; ACES entries follow :func:`_aces_launchable`.
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


def get_scenario_detail(scenario_id: str) -> dict[str, Any]:
    """Get a single scenario by ID from either source.

    Checks the database first, then falls back to YAML.

    Args:
        scenario_id: Unique scenario identifier.

    Returns:
        Scenario dict with metadata overlay.

    Raises:
        ValueError: If scenario not found in either source.
    """
    metadata_map = _get_metadata_map()
    meta = metadata_map.get(scenario_id)

    # Try database first
    from cms.models import Scenario

    try:
        db_scenario = Scenario.objects.get(scenario_id=scenario_id)
        template = db_scenario.to_template()
        return _scenario_to_dict(template, is_default=False, metadata=meta)
    except Scenario.DoesNotExist:
        pass

    # Fall back to YAML
    try:
        template = load_yaml_scenario(scenario_id)
        return _scenario_to_dict(template, is_default=True, metadata=meta)
    except ValueError as e:
        raise ValueError(f"Scenario '{scenario_id}' not found") from e


def load_demo_scenario_template(scenario_id: str) -> ScenarioTemplate:
    """Load a demo scenario template for hydration and agent-requirement checks."""
    template = load_scenario_template(scenario_id)
    if isinstance(template, CTFScenarioTemplate):
        raise ValueError(f"Scenario '{scenario_id}' is a CTF scenario")
    return template


def check_scenario_access(scenario_id: str, user: User) -> dict[str, Any]:
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


def load_scenario_template(scenario_id: str) -> AnyScenarioTemplate:
    """Load a ScenarioTemplate from either source for hydration.

    This is the replacement for loader.load_scenario() that checks
    the database first.

    Args:
        scenario_id: Unique scenario identifier.

    Returns:
        Validated scenario template (demo or CTF).

    Raises:
        ValueError: If scenario not found in either source.
    """
    # Try database first
    from cms.models import Scenario

    try:
        db_scenario = Scenario.objects.get(scenario_id=scenario_id)
        return db_scenario.to_template()
    except Scenario.DoesNotExist:
        pass

    # Fall back to YAML
    return load_yaml_scenario(scenario_id)
