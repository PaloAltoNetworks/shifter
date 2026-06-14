"""Common scenario-editor service helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from risk_register.models import AuditLog
from risk_register.services import AuditEvent, audit_log
from shared.auth import validate_cms_authoring_user
from shared.exceptions import CMSError

if TYPE_CHECKING:
    from django.contrib.auth.models import User


class ScenarioEditorError(CMSError):
    """Error raised by scenario editor operations."""

    @property
    def public_message(self) -> str:
        """Return the user-facing service message without debug details."""
        return self.message


def validate_user(user: User, func_name: str) -> None:
    """Delegate to the shared CMS authoring user validator."""
    validate_cms_authoring_user(user, func_name)


def audit_scenario_change(
    *,
    action: str,
    actor_id: int,
    state: dict[str, object],
    previous: bool = False,
) -> None:
    """Write the minimal scenario audit record used by editor mutations."""
    if previous:
        audit_log(
            AuditEvent(
                entity_type=AuditLog.EntityType.SCENARIO,
                # Scenario PKs are UUIDs and ScenarioMetadata PKs are ints;
                # existing audit records use 0 and carry scenario_id in state.
                entity_id=0,
                action=action,
                actor_type=AuditLog.ActorType.USER,
                actor_id=actor_id,
                previous_state=state,
            )
        )
    else:
        audit_log(
            AuditEvent(
                entity_type=AuditLog.EntityType.SCENARIO,
                entity_id=0,
                action=action,
                actor_type=AuditLog.ActorType.USER,
                actor_id=actor_id,
                new_state=state,
            )
        )
