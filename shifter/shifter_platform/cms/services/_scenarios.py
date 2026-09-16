"""Scenario service entrypoints (list / get / validate)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cms.exceptions import CMSError
from cms.models import AgentConfig

from ._common import _validate_caller_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from shared.schemas.cms_projections import ScenarioProjection

logger = logging.getLogger(__name__)


def list_scenarios(user: User) -> list[ScenarioProjection]:
    """Get available scenarios with metadata.

    Uses the RAES package-source registry with metadata overlays and access
    filtering.

    Args:
        user: User requesting scenarios

    Returns:
        List of scenario dictionaries with id, name, description,
        requirements, instances, is_default, enabled, staff_only fields.

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user is unsaved
    """
    from cms.scenarios.registry import list_all_scenarios

    _validate_caller_user(user, "list_scenarios")

    logger.debug("list_scenarios called for user_id=%s", user.id)

    try:
        result = list_all_scenarios(user=user)

        logger.debug(
            "list_scenarios returning %d scenarios for user_id=%s",
            len(result),
            user.id,
        )
        return result

    except Exception:
        logger.exception(
            "Error in list_scenarios for user_id=%s",
            user.id,
        )
        raise


def list_launchable_scenarios(user: User, workflow: str = "range_launch") -> list[ScenarioProjection]:
    """Get scenarios a given launch workflow may consume.

    Staff review listings (the full catalog) use ``list_scenarios``; launch,
    CTF event, CTF participant, and experiment selection paths use this so they
    never offer or accept a non-launchable RAES entry.

    Args:
        user: User requesting scenarios.
        workflow: A ``ScenarioWorkflow`` value (defaults to range launch).

    Returns:
        List of launchable scenario dicts for the workflow.

    Raises:
        TypeError: If user is None or invalid type.
        ValueError: If user is unsaved.
    """
    from cms.scenarios.registry import ScenarioWorkflow
    from cms.scenarios.registry import list_launchable_scenarios as _registry_list_launchable

    _validate_caller_user(user, "list_launchable_scenarios")

    try:
        result = _registry_list_launchable(user=user, workflow=ScenarioWorkflow(workflow))
        logger.debug(
            "list_launchable_scenarios returning %d scenarios for user_id=%s workflow=%s",
            len(result),
            user.id,
            workflow,
        )
        return result
    except Exception:
        logger.exception("Error in list_launchable_scenarios for user_id=%s", user.id)
        raise


def get_scenario(scenario_id: str) -> ScenarioProjection:
    """Get a single scenario template by ID.

    Uses the RAES package-source registry.

    Args:
        scenario_id: Unique scenario identifier

    Returns:
        Scenario dictionary with id, name, description, requirements,
        instances, is_default, enabled, staff_only fields.

    Raises:
        CMSError: If scenario not found
    """
    from cms.scenarios.registry import get_scenario_detail

    logger.debug("get_scenario called for scenario_id=%s", scenario_id)

    try:
        return get_scenario_detail(scenario_id)

    except ValueError as e:
        logger.error("get_scenario: scenario '%s' not found", scenario_id)
        raise CMSError(f"Scenario '{scenario_id}' not found") from e
    except Exception:
        logger.exception(
            "Error in get_scenario for scenario_id=%s",
            scenario_id,
        )
        raise


def validate_scenario_requirements(scenario_id: str, agent: AgentConfig | None) -> None:
    """Validate that a registered RAES scenario is available for launch.

    Args:
        scenario_id: Scenario to validate against
        agent: AgentConfig instance (or None)

    Returns:
        None if validation passes

    Raises:
        CMSError: If validation fails (agent missing, wrong OS, etc.)
    """
    from cms.scenarios.registry import is_scenario_launchable

    del agent

    logger.debug(
        "validate_scenario_requirements called for scenario_id=%s",
        scenario_id,
    )

    if not is_scenario_launchable(scenario_id):
        logger.error(
            "validate_scenario_requirements: scenario '%s' is not launchable",
            scenario_id,
        )
        raise CMSError(f"Scenario '{scenario_id}' is not available for launch")

    logger.debug(
        "validate_scenario_requirements: validation passed for scenario_id=%s",
        scenario_id,
    )
