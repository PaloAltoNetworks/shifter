"""Scenario editor CRUD coordinators."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cms.scenarios.registry import get_scenario_detail, is_default_scenario
from risk_register.models import AuditLog
from shared.log_sanitize import safe_log_value

from ._common import ScenarioEditorError, audit_scenario_change, validate_user
from ._persistence import (
    create_custom_scenario,
    ensure_custom_scenario_id,
    get_custom_scenario_or_raise,
    save_scenario_updates,
    soft_delete_scenario,
)
from ._validation import validate_scenario_id, validate_scenario_payload

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import Scenario

logger = logging.getLogger(__name__)


def _raise_invalid_definition(errors: list[str]) -> None:
    raise ScenarioEditorError(f"Invalid scenario definition: {'; '.join(errors)}")


def _candidate_update_payload(
    scenario: Scenario,
    *,
    name: str | None,
    description: str | None,
    definition: dict[str, Any] | None,
) -> tuple[str, str, dict[str, Any]]:
    return (
        scenario.name if name is None else name,
        scenario.description if description is None else description,
        scenario.definition if definition is None else definition,
    )


def create_scenario(
    user: User,
    *,
    scenario_id: str,
    name: str,
    description: str,
    definition: dict[str, Any],
) -> Scenario:
    """Create a new custom scenario."""
    validate_user(user, "create_scenario")
    logger.debug(
        "create_scenario called for user_id=%s, scenario_id=%s",
        user.id,
        safe_log_value(scenario_id),
    )

    try:
        try:
            validate_scenario_id(scenario_id)
        except ScenarioEditorError:
            logger.error(
                "create_scenario: invalid scenario_id format: %s, user_id=%s",
                safe_log_value(scenario_id),
                user.id,
            )
            raise

        if is_default_scenario(scenario_id):
            logger.error(
                "create_scenario: conflicts with default scenario, scenario_id=%s, user_id=%s",
                safe_log_value(scenario_id),
                user.id,
            )
            raise ScenarioEditorError(f"Scenario ID '{scenario_id}' conflicts with a built-in default scenario")

        errors = validate_scenario_payload(
            scenario_id=scenario_id,
            name=name,
            description=description,
            definition=definition,
        )
        if errors:
            logger.error(
                "create_scenario: invalid definition, scenario_id=%s, user_id=%s",
                safe_log_value(scenario_id),
                user.id,
            )
            _raise_invalid_definition(errors)

        scenario = create_custom_scenario(
            user,
            scenario_id=scenario_id,
            name=name,
            description=description,
            definition=definition,
        )
    except (TypeError, ValueError, ScenarioEditorError):
        raise
    except Exception:
        logger.exception(
            "Error in create_scenario for user_id=%s, scenario_id=%s",
            user.id,
            safe_log_value(scenario_id),
        )
        raise

    audit_scenario_change(
        action=AuditLog.Action.CREATE,
        actor_id=user.id,
        state={"scenario_id": scenario_id, "name": name},
    )
    logger.info("Scenario created: scenario_id=%s by user_id=%s", safe_log_value(scenario_id), user.id)
    return scenario


def update_scenario(
    user: User,
    scenario_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    definition: dict[str, Any] | None = None,
) -> Scenario:
    """Update an existing custom scenario."""
    validate_user(user, "update_scenario")
    logger.debug(
        "update_scenario called for user_id=%s, scenario_id=%s",
        user.id,
        safe_log_value(scenario_id),
    )

    try:
        ensure_custom_scenario_id(scenario_id, action="update_scenario", user_id=user.id)
        scenario = get_custom_scenario_or_raise(scenario_id, action="update_scenario", user_id=user.id)
        next_name, next_description, next_definition = _candidate_update_payload(
            scenario,
            name=name,
            description=description,
            definition=definition,
        )
        errors = validate_scenario_payload(
            scenario_id=scenario.scenario_id,
            name=next_name,
            description=next_description,
            definition=next_definition,
        )
        if errors:
            logger.error(
                "update_scenario: invalid definition, scenario_id=%s, user_id=%s",
                safe_log_value(scenario_id),
                user.id,
            )
            _raise_invalid_definition(errors)

        scenario = save_scenario_updates(
            scenario,
            user,
            name=name,
            description=description,
            definition=definition,
        )
    except (TypeError, ScenarioEditorError):
        raise
    except Exception:
        logger.exception(
            "Error in update_scenario for user_id=%s, scenario_id=%s",
            user.id,
            safe_log_value(scenario_id),
        )
        raise

    audit_scenario_change(
        action=AuditLog.Action.UPDATE,
        actor_id=user.id,
        state={"scenario_id": scenario_id, "name": scenario.name},
    )
    logger.info("Scenario updated: scenario_id=%s by user_id=%s", safe_log_value(scenario_id), user.id)
    return scenario


def delete_scenario(user: User, scenario_id: str) -> None:
    """Soft-delete a custom scenario."""
    validate_user(user, "delete_scenario")
    logger.debug(
        "delete_scenario called for user_id=%s, scenario_id=%s",
        user.id,
        safe_log_value(scenario_id),
    )

    try:
        ensure_custom_scenario_id(scenario_id, action="delete_scenario", user_id=user.id)
        scenario = get_custom_scenario_or_raise(scenario_id, action="delete_scenario", user_id=user.id)
        soft_delete_scenario(scenario, user)
    except (TypeError, ScenarioEditorError):
        raise
    except Exception:
        logger.exception(
            "Error in delete_scenario for user_id=%s, scenario_id=%s",
            user.id,
            safe_log_value(scenario_id),
        )
        raise

    audit_scenario_change(
        action=AuditLog.Action.DELETE,
        actor_id=user.id,
        state={"scenario_id": scenario_id, "name": scenario.name},
        previous=True,
    )
    logger.info("Scenario deleted: scenario_id=%s by user_id=%s", safe_log_value(scenario_id), user.id)


def clone_scenario(
    user: User,
    source_scenario_id: str,
    *,
    new_scenario_id: str,
    new_name: str | None = None,
) -> Scenario:
    """Clone an existing scenario into a new custom scenario."""
    validate_user(user, "clone_scenario")
    logger.debug(
        "clone_scenario called for user_id=%s, source=%s, new_id=%s",
        user.id,
        safe_log_value(source_scenario_id),
        safe_log_value(new_scenario_id),
    )

    try:
        source = get_scenario_detail(source_scenario_id)
    except ValueError as e:
        logger.error(
            "clone_scenario: source not found, source_scenario_id=%s, user_id=%s",
            safe_log_value(source_scenario_id),
            user.id,
        )
        raise ScenarioEditorError(f"Source scenario '{source_scenario_id}' not found") from e

    definition = {
        "instances": source.get("instances", []),
        "subnets": source.get("subnets", []),
        "ngfw": source.get("ngfw", False),
    }
    return create_scenario(
        user,
        scenario_id=new_scenario_id,
        name=new_name or f"Copy of {source['name']}",
        description=source.get("description", ""),
        definition=definition,
    )
