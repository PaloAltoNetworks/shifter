"""Scenario service entrypoints (list / get / validate)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cms.exceptions import CMSError
from cms.models import AgentConfig

from ._common import _validate_caller_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def list_scenarios(user: User) -> list[dict[str, Any]]:
    """Get available scenarios with metadata.

    Uses the scenario registry to combine YAML defaults and DB customs,
    applying metadata overlays and access filtering.

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


def get_scenario(scenario_id: str) -> dict[str, Any]:
    """Get a single scenario template by ID.

    Uses the scenario registry to check DB first, then YAML.

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
    """Validate that an agent meets scenario requirements.

    Args:
        scenario_id: Scenario to validate against
        agent: AgentConfig instance (or None)

    Returns:
        None if validation passes

    Raises:
        CMSError: If validation fails (agent missing, wrong OS, etc.)
    """
    from cms.scenarios.registry import load_scenario_template

    logger.debug(
        "validate_scenario_requirements called for scenario_id=%s",
        scenario_id,
    )

    try:
        scenario = load_scenario_template(scenario_id)
    except ValueError as e:
        logger.error(
            "validate_scenario_requirements: scenario '%s' not found",
            scenario_id,
        )
        raise CMSError(f"Scenario '{scenario_id}' not found") from e

    if scenario.requires_agent() and agent is None:
        logger.error(
            "validate_scenario_requirements: scenario '%s' requires an agent",
            scenario_id,
        )
        raise CMSError(f"Scenario '{scenario_id}' requires an agent")

    logger.debug(
        "validate_scenario_requirements: validation passed for scenario_id=%s",
        scenario_id,
    )
