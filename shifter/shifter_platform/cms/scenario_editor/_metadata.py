"""ScenarioMetadata service operations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cms.models import ScenarioMetadata
from cms.scenarios.registry import get_scenario_detail
from risk_register.models import AuditLog
from shared.log_sanitize import safe_log_value

from ._common import ScenarioEditorError, audit_scenario_change, validate_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def _verify_scenario_exists(scenario_id: str, *, user_id: int) -> None:
    """Confirm the scenario exists in the registry before metadata changes."""
    try:
        get_scenario_detail(scenario_id)
    except ValueError as e:
        logger.error(
            "update_metadata: scenario not found, scenario_id=%s, user_id=%s",
            safe_log_value(scenario_id),
            user_id,
        )
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found") from e


def update_metadata(
    user: User,
    scenario_id: str,
    *,
    enabled: bool | None = None,
    staff_only: bool | None = None,
) -> ScenarioMetadata:
    """Update metadata for a YAML default or DB-backed custom scenario."""
    validate_user(user, "update_metadata")
    logger.debug(
        "update_metadata called for user_id=%s, scenario_id=%s",
        user.id,
        safe_log_value(scenario_id),
    )

    try:
        _verify_scenario_exists(scenario_id, user_id=user.id)

        metadata, created = ScenarioMetadata.objects.get_or_create(
            scenario_id=scenario_id,
            defaults={
                "enabled": enabled if enabled is not None else True,
                "staff_only": staff_only if staff_only is not None else False,
                "updated_by": user,
            },
        )

        if not created:
            update_fields = ["updated_by", "updated_at"]
            if enabled is not None:
                metadata.enabled = enabled
                update_fields.append("enabled")
            if staff_only is not None:
                metadata.staff_only = staff_only
                update_fields.append("staff_only")
            metadata.updated_by = user
            metadata.save(update_fields=update_fields)
    except (TypeError, ScenarioEditorError):
        raise
    except Exception:
        logger.exception(
            "Error in update_metadata for user_id=%s, scenario_id=%s",
            user.id,
            safe_log_value(scenario_id),
        )
        raise

    audit_scenario_change(
        action=AuditLog.Action.UPDATE,
        actor_id=user.id,
        state={"scenario_id": scenario_id, "enabled": metadata.enabled, "staff_only": metadata.staff_only},
    )
    logger.info(
        "Scenario metadata updated: scenario_id=%s, enabled=%s, staff_only=%s by user_id=%s",
        safe_log_value(scenario_id),
        metadata.enabled,
        metadata.staff_only,
        user.id,
    )
    return metadata
