"""Scenario registry - unified access to YAML defaults and DB customs.

Merges scenario templates from two sources:
1. YAML files in cms/scenarios/templates/ (defaults, code-managed)
2. Scenario model instances in the database (staff-created customs)

Applies ScenarioMetadata overlays (enabled, staff_only) to all scenarios.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cms.scenarios.loader import get_all_scenarios as get_yaml_scenarios
from cms.scenarios.loader import list_scenario_ids as list_yaml_ids
from cms.scenarios.loader import load_scenario as load_yaml_scenario
from cms.scenarios.schema import ScenarioTemplate

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def _get_metadata_map() -> dict[str, dict[str, Any]]:
    """Load all ScenarioMetadata rows as a dict keyed by scenario_id.

    Returns:
        {scenario_id: {"enabled": bool, "staff_only": bool}, ...}
    """
    from cms.models import ScenarioMetadata

    return {m.scenario_id: {"enabled": m.enabled, "staff_only": m.staff_only} for m in ScenarioMetadata.objects.all()}


def _get_db_scenarios() -> list[ScenarioTemplate]:
    """Load all active (non-deleted) custom scenarios from the database.

    Returns:
        List of ScenarioTemplate objects built from Scenario model instances.
    """
    from cms.models import Scenario

    scenarios = []
    for s in Scenario.objects.filter(deleted_at__isnull=True):
        try:
            scenarios.append(s.to_template())
        except Exception:
            logger.warning(
                "Skipping invalid DB scenario: scenario_id=%s, id=%s",
                s.scenario_id,
                s.id,
            )
    return scenarios


def is_default_scenario(scenario_id: str) -> bool:
    """Check if a scenario_id corresponds to a YAML default.

    Args:
        scenario_id: The scenario identifier to check.

    Returns:
        True if the scenario exists as a YAML file in templates/.
    """
    return scenario_id in list_yaml_ids()


def _scenario_to_dict(
    template: ScenarioTemplate,
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
    data["agent_requirements"] = template.get_agent_requirements()
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
    result = []

    # YAML defaults
    yaml_ids = set()
    for template in get_yaml_scenarios():
        yaml_ids.add(template.id)
        meta = metadata_map.get(template.id)
        entry = _scenario_to_dict(template, is_default=True, metadata=meta)
        result.append(entry)

    # DB customs (skip any whose scenario_id collides with a YAML default)
    for template in _get_db_scenarios():
        if template.id in yaml_ids:
            logger.warning(
                "DB scenario '%s' collides with YAML default, skipping",
                template.id,
            )
            continue
        meta = metadata_map.get(template.id)
        entry = _scenario_to_dict(template, is_default=False, metadata=meta)
        result.append(entry)

    # Access filtering
    if user is not None and not (user.is_staff or user.is_superuser):
        result = [s for s in result if s["enabled"] and not s["staff_only"]]

    # Sort by name
    result.sort(key=lambda s: s["name"])
    return result


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
        db_scenario = Scenario.objects.get(
            scenario_id=scenario_id,
            deleted_at__isnull=True,
        )
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


def load_scenario_template(scenario_id: str) -> ScenarioTemplate:
    """Load a ScenarioTemplate from either source for hydration.

    This is the replacement for loader.load_scenario() that checks
    the database first.

    Args:
        scenario_id: Unique scenario identifier.

    Returns:
        Validated ScenarioTemplate.

    Raises:
        ValueError: If scenario not found in either source.
    """
    # Try database first
    from cms.models import Scenario

    try:
        db_scenario = Scenario.objects.get(
            scenario_id=scenario_id,
            deleted_at__isnull=True,
        )
        return db_scenario.to_template()
    except Scenario.DoesNotExist:
        pass

    # Fall back to YAML
    return load_yaml_scenario(scenario_id)
