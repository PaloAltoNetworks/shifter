"""Side effects of an applied operation result (ADR-043 phase 4, #1836).

Split out of ``_operation_apply_domain`` to keep both modules under the file-size
gate. These are the writes an applied transition implies beyond the status
itself: the strict audit row that makes the transition auditable (ADR-043-R3) and
the ADR-025 notifications the provisioner used to enqueue directly.

Everything here runs inside the caller's transaction, so a failure rolls the
whole apply back rather than leaving a transition without its audit or a
notification without the state it describes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from django.utils import timezone

from shared.audit import AuditActorType, AuditEvent, audit_log
from shared.enums import ResourceStatus

if TYPE_CHECKING:
    from engine.models import App, Instance, Range

_AUDIT_SOURCE = "engine.services.operation_apply"


def _audit(
    entity_type: str,
    entity_id: int,
    new: str,
    *,
    request_id: str,
    previous: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    context: str = "",
) -> None:
    """Write the transition's audit row strictly, inside the caller's transaction.

    Builds the event and calls ``audit_log(..., strict=True)`` directly rather
    than going through ``audit_log_system_event``: the shared helper is
    best-effort by contract, and here the audit row is the control -- if it
    cannot be written the transition must not survive (ADR-043-R3).

    ``entity_id`` is 0 for UUID-identified entities (NGFW): ``AuditLog.entity_id``
    is a PositiveIntegerField, so passing a UUID there raises and loses the row.
    The UUIDs go in the state instead — the same convention ``engine.handlers``
    already uses.
    """
    from engine.handlers._audit import _status_to_action

    full_context = f"[{_AUDIT_SOURCE}] {context}" if context else f"[{_AUDIT_SOURCE}]"
    audit_log(
        AuditEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            action=_status_to_action(new),
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            previous_state=previous or {},
            new_state={"status": new, **(detail or {})},
            context=full_context,
            request_id=request_id,
        ),
        strict=True,
    )


def _enqueue_range_status_event(range_obj: Range, new_status: str, error_message: str) -> None:
    """Enqueue the ADR-025 range status notification for an applied transition."""
    from engine.models import RangeEventOutbox
    from shared.messages.events import EVENT_TYPE_STATUS_UPDATED

    event_id = uuid4()
    related_request = range_obj.request
    RangeEventOutbox.objects.create(
        event_id=event_id,
        event_type=EVENT_TYPE_STATUS_UPDATED,
        payload={
            "event_type": EVENT_TYPE_STATUS_UPDATED,
            "event_id": str(event_id),
            "timestamp": timezone.now().isoformat(),
            "request_id": str(related_request.request_id) if related_request is not None else "",
            "range_id": range_obj.id,
            "user_id": range_obj.user_id,
            "new_status": new_status,
            "error_message": error_message,
        },
        next_attempt_at=timezone.now(),
    )


def _enqueue_ngfw_status_event(ngfw: Instance, app: App | None, new_status: str, request_id: str) -> None:
    """Enqueue the NGFW lifecycle notification for an applied transition.

    The provisioner used to write this row itself (``events.publish_ngfw_event``).
    After cutover the notification belongs to the applier, committed in the same
    transaction as the state it describes, so a consumer can never observe an
    event for a transition that rolled back. Same notification-only shape as
    before: identifiers and status, no state.
    """
    from engine.models import RangeEventOutbox
    from shared.messages.events import EVENT_TYPE_NGFW

    event_id = uuid4()
    RangeEventOutbox.objects.create(
        event_id=event_id,
        event_type=EVENT_TYPE_NGFW,
        payload={
            "event_type": EVENT_TYPE_NGFW,
            "event_id": str(event_id),
            "timestamp": timezone.now().isoformat(),
            "request_id": request_id,
            "instance_id": str(ngfw.uuid),
            "app_id": str(app.uuid) if app is not None else None,
            "status": new_status,
        },
        next_attempt_at=timezone.now(),
    )


def _save_status(obj: Range | Instance | App, new_status: str, extra_fields: dict[str, Any] | None = None) -> str:
    """Set status (+ timestamps) on a locked row and return the previous status."""
    previous = obj.status
    now = timezone.now()
    obj.status = new_status
    obj.updated_at = now
    update_fields = ["status", "updated_at"]
    for field, value in (extra_fields or {}).items():
        setattr(obj, field, value)
        update_fields.append(field)
    obj.save(update_fields=update_fields)
    return previous


def _terminal_timestamps(new_status: str) -> dict[str, Any]:
    """Return the timestamp columns a terminal status also sets."""
    if new_status == ResourceStatus.DESTROYED.value:
        return {"destroyed_at": timezone.now()}
    return {}
