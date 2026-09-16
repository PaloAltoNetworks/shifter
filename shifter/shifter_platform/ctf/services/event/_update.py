"""CTF event update transaction split from the broader CRUD service."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.db import transaction

from ctf.exceptions import CTFNotFoundError, CTFStateError
from ctf.models import CTFEvent
from shared.log_sanitize import safe_log_value

from ._crud import (
    _EVENT_MUTABLE_FIELDS,
    _reject_team_config_changes_after_start,
    _reschedule_event_if_schedule_changed,
    _validate_event_time_range,
)
from ._validation import validate_scoring_mode

logger = logging.getLogger(__name__)


def _authorize_event_update(event: CTFEvent, actor_id: int | None) -> None:
    """Require the event configuration capability when an actor is supplied."""
    if actor_id is None:
        return
    from ctf.enums import EventCapability
    from ctf.services.authorization import assert_event_capability

    assert_event_capability(actor_id, event, EventCapability.CONFIG)


def _validate_event_update(event: CTFEvent, event_data: dict[str, Any]) -> None:
    """Validate event state and cross-field invariants before mutation."""
    _reject_team_config_changes_after_start(event, event_data)
    if not event.is_modifiable:
        raise CTFStateError(
            f"Event cannot be modified in {event.status} state",
            details={"event_id": str(event.id), "status": event.status},
        )
    _validate_event_time_range(
        event_data.get("event_start", event.event_start),
        event_data.get("event_end", event.event_end),
    )
    validate_scoring_mode(event_data)


def _safe_event_update_data(event: CTFEvent, event_data: dict[str, Any]) -> dict[str, Any]:
    """Filter organizer fields and reject scenario changes after hydration."""
    safe_data = {key: value for key, value in event_data.items() if key in _EVENT_MUTABLE_FIELDS}
    if "scenario_id" in safe_data and safe_data["scenario_id"] != event.scenario_id:
        from ctf.models import CTFContentHydrationReceipt

        if CTFContentHydrationReceipt.objects.filter(event=event).exists():
            raise CTFStateError(
                "A hydrated event cannot change scenarios.",
                code="CTF_CONTENT_SCENARIO_IMMUTABLE",
            )
    return safe_data


def _audit_public_registration_update(
    event: CTFEvent,
    *,
    actor_id: int | None,
    was_enabled: bool,
) -> None:
    """Audit an organizer-visible publication transition."""
    if actor_id is None or event.public_registration_enabled == was_enabled:
        return
    from ctf.services.audit import audit_public_registration_publication

    audit_public_registration_publication(
        actor_id=actor_id,
        event_id=event.pk,
        enabled=event.public_registration_enabled,
    )


def update_event(event_id: UUID, event_data: dict[str, Any], *, actor_id: int | None = None) -> CTFEvent:
    """Update an existing CTF event under the event row lock."""
    logger.info("Updating CTF event %s", safe_log_value(event_id))

    with transaction.atomic():
        try:
            event = CTFEvent.objects.select_for_update().get(pk=event_id)
        except CTFEvent.DoesNotExist:
            raise CTFNotFoundError(
                f"Event {event_id} not found",
                details={"event_id": str(event_id)},
            ) from None

        _authorize_event_update(event, actor_id)
        _validate_event_update(event, event_data)
        safe_data = _safe_event_update_data(event, event_data)
        old_event_start = event.event_start
        old_event_end = event.event_end
        cleanup_may_change = bool({"event_end", "cleanup_delay_hours"} & safe_data.keys())
        old_cleanup_time = event.get_cleanup_time() if cleanup_may_change else None
        public_registration_was_enabled = event.public_registration_enabled

        for key, value in safe_data.items():
            setattr(event, key, value)
        event.save()

        _audit_public_registration_update(
            event,
            actor_id=actor_id,
            was_enabled=public_registration_was_enabled,
        )

        logger.info("Updated CTF event %s", event.id)
        _reschedule_event_if_schedule_changed(
            event,
            safe_data,
            old_event_start=old_event_start,
            old_event_end=old_event_end,
            old_cleanup_time=old_cleanup_time,
        )

    return event
