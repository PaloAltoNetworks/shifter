"""Scenario-editor persistence helpers for custom scenarios."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError

from cms.models import Scenario, ScenarioMetadata
from cms.scenarios.registry import is_default_scenario
from shared.log_sanitize import safe_log_value

from ._common import ScenarioEditorError

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def ensure_custom_scenario_id(scenario_id: str, *, action: str, user_id: int) -> None:
    """Reject edits that target code-managed default scenarios."""
    if not is_default_scenario(scenario_id):
        return

    logger.error(
        "%s: cannot mutate default scenario, scenario_id=%s, user_id=%s",
        action,
        safe_log_value(scenario_id),
        user_id,
    )
    verb = "edit" if action == "update_scenario" else "delete"
    raise ScenarioEditorError(f"Cannot {verb} default scenario '{scenario_id}'. Default scenarios are managed in code.")


def create_custom_scenario(
    user: User,
    *,
    scenario_id: str,
    name: str,
    description: str,
    definition: dict[str, Any],
) -> Scenario:
    """Persist a new custom scenario after caller-side validation."""
    try:
        with transaction.atomic():
            if Scenario.objects.filter(scenario_id=scenario_id).exists():
                logger.error(
                    "create_scenario: duplicate scenario_id=%s, user_id=%s",
                    safe_log_value(scenario_id),
                    user.id,
                )
                raise ScenarioEditorError(f"A scenario with ID '{scenario_id}' already exists")

            scenario = Scenario(
                scenario_id=scenario_id,
                name=name,
                description=description,
                definition=definition,
                created_by=user,
                updated_by=user,
            )
            try:
                scenario.save()
            except PydanticValidationError as e:
                raise ScenarioEditorError(f"Invalid scenario definition: {e}") from e
    except IntegrityError:
        logger.error(
            "create_scenario: integrity error (race), scenario_id=%s, user_id=%s",
            safe_log_value(scenario_id),
            user.id,
        )
        raise ScenarioEditorError(f"A scenario with ID '{scenario_id}' already exists") from None

    return scenario


def get_custom_scenario_or_raise(
    scenario_id: str,
    *,
    action: str,
    user_id: int,
) -> Scenario:
    """Load an active custom scenario or raise a service-layer error."""
    try:
        return Scenario.objects.get(scenario_id=scenario_id)
    except Scenario.DoesNotExist as e:
        logger.error(
            "%s: scenario not found, scenario_id=%s, user_id=%s",
            action,
            safe_log_value(scenario_id),
            user_id,
        )
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found") from e


def save_scenario_updates(
    scenario: Scenario,
    user: User,
    *,
    name: str | None = None,
    description: str | None = None,
    definition: dict[str, Any] | None = None,
) -> Scenario:
    """Apply and persist caller-validated scenario updates."""
    update_fields = ["updated_by", "updated_at"]
    if name is not None:
        scenario.name = name
        update_fields.append("name")
    if description is not None:
        scenario.description = description
        update_fields.append("description")
    if definition is not None:
        scenario.definition = definition
        update_fields.append("definition")

    scenario.updated_by = user
    try:
        scenario.save(update_fields=update_fields)
    except PydanticValidationError as e:
        raise ScenarioEditorError(f"Invalid scenario definition: {e}") from e

    return scenario


def soft_delete_scenario(scenario: Scenario, user: User) -> None:
    """Soft-delete a custom scenario and remove any metadata overlay."""
    scenario.deleted_at = timezone.now()
    scenario.updated_by = user
    scenario.save(update_fields=["deleted_at", "updated_by", "updated_at"])
    ScenarioMetadata.objects.filter(scenario_id=scenario.scenario_id).delete()
