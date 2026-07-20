"""Argument-shape and scenario admission validators for range creation.

Split out of ``_range_create`` (Sonar S104), following the
``_range_backend_admission`` precedent, so the create pipeline module stays
within its size budget.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cms.exceptions import CMSError
from shared.constants import USER_CANNOT_BE_NONE, USER_MUST_BE_SAVED

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.scenarios.schema import ScenarioTemplate

logger = logging.getLogger(__name__)


def _validate_create_range_user(user: User) -> None:
    """Validate the ``user`` argument shape for create_range."""
    if user is None:
        logger.error("create_range called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)
    if not hasattr(user, "id"):
        logger.error(
            "create_range called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)
    if user.id is None:
        logger.error("create_range called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)


def _validate_create_range_scenario(user: User, scenario: str) -> None:
    """Validate the ``scenario`` argument shape for create_range."""
    if scenario is None:
        logger.error(
            "create_range called with None scenario for user_id=%s",
            user.id,
        )
        raise ValueError("scenario cannot be None")
    if not isinstance(scenario, str) or not scenario:
        logger.error(
            "create_range called with invalid scenario '%s' for user_id=%s",
            scenario,
            user.id,
        )
        raise ValueError("scenario must be a non-empty string")


def _validate_create_range_agents_by_os(user: User, agents_by_os: dict[str, int]) -> None:
    """Validate the ``agents_by_os`` argument shape for create_range."""
    if agents_by_os is None:
        logger.error(
            "create_range called with None agents_by_os for user_id=%s",
            user.id,
        )
        raise TypeError("agents_by_os cannot be None")
    if not isinstance(agents_by_os, dict):
        logger.error(
            "create_range called with invalid agents_by_os type: %s",
            type(agents_by_os).__name__,
        )
        msg = f"agents_by_os must be a dict, got {type(agents_by_os).__name__}"
        raise TypeError(msg)


def _assert_scenario_launchable(scenario: str) -> None:
    """Reject a known-but-non-launchable scenario before hydration.

    Unknown ids are left to ``_load_scenario_template_or_raise`` (which raises
    the not-found CMSError), preserving existing behavior. Legacy YAML/DB
    entries are always launchable; a non-launchable ACES entry (pending
    conformance, unsupported profile, invalid refs, or a shadowed legacy id)
    is rejected here with a clear error instead of an opaque not-found.
    """
    from cms.scenarios.registry import get_catalog_entry

    entry = get_catalog_entry(scenario)
    if entry is not None and not entry.get("launchable", True):
        logger.warning("create_range: scenario '%s' is not launchable", scenario)
        raise CMSError(f"Scenario '{scenario}' is not available for launch")


def _load_scenario_template_or_raise(scenario: str) -> ScenarioTemplate:
    """Return the demo scenario template or raise CMSError if not found."""
    from cms.scenarios.registry import load_demo_scenario_template

    try:
        return load_demo_scenario_template(scenario)
    except ValueError as e:
        logger.error("create_range: scenario '%s' not found", scenario)
        raise CMSError(str(e)) from e


def _check_scenario_agent_requirements(
    scenario: str, requirements: dict[str, bool], agents_by_os: dict[str, int]
) -> None:
    """Raise CMSError when scenario requirements are not met by agents_by_os."""
    if requirements["requires_windows"] and "windows" not in agents_by_os:
        raise CMSError(f"Scenario '{scenario}' requires a Windows agent")
    if requirements["requires_linux"] and "linux" not in agents_by_os:
        raise CMSError(f"Scenario '{scenario}' requires a Linux agent")
    if requirements["has_from_agent"] and not agents_by_os:
        raise CMSError(f"Scenario '{scenario}' requires at least one agent")
