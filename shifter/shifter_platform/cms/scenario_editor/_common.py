"""Common scenario-editor service helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.audit import (
    AuditActorType,
    AuditEntityType,
    AuditEvent,
    audit_log,
)
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
                entity_type=AuditEntityType.SCENARIO,
                # Catalog identities are strings; audit records carry the
                # scenario_id in state and use the established neutral entity id.
                entity_id=0,
                action=action,
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                previous_state=state,
            )
        )
    else:
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.SCENARIO,
                entity_id=0,
                action=action,
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                new_state=state,
            )
        )
