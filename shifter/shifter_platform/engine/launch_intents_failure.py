"""Dispatch-failure lifecycle for provisioner launch intents.

Split out of :mod:`engine.launch_intents` (Sonar S104) alongside the earlier
``operation_inputs`` split. Owns the "a provider dispatch failed, close the
episode" concern: resolving and locking the failed domain row, confirming the
failure still owns the current generation, and persisting the sanitized FAILED
projection plus its status event. The two public entry points are re-exported
from :mod:`engine.launch_intents` so existing importers are unaffected.

Imports of ``authorize_provisioner_payload`` / ``command_from_payload`` back from
``launch_intents`` are deferred (function-local) so the top-level import graph
stays one-directional (``launch_intents`` -> this module).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from django.utils import timezone

from engine.models import Instance, Range, Request

PROVISIONER_DISPATCH_FAILED = "Provisioner dispatch failed"


def clear_provisioner_operation_after_failure(row: Range | Instance) -> list[str]:
    """Close a failed lifecycle episode so the same operation can be retried."""
    if row.provisioner_operation_id is None and not row.provisioner_operation:
        return []
    row.provisioner_operation = ""
    row.provisioner_operation_id = None
    return ["provisioner_operation", "provisioner_operation_id"]


def _resolve_failure_target(payload: dict[str, object]) -> Range | Instance | None:
    """Lock the domain row named by a validated failure payload."""
    target: Range | Instance | None
    if "request_id" not in payload:
        target = Range.objects.select_for_update().filter(pk=int(str(payload["range_id"]))).first()
    else:
        request = Request.objects.filter(request_id=UUID(str(payload["request_id"]))).first()
        if request is None:
            target = None
        elif payload.get("resource") in {"range", "raes-range"}:
            target = Range.objects.select_for_update().filter(request=request).first()
        else:
            target = Instance.objects.select_for_update().filter(request=request, role=Instance.Role.NGFW).first()
    return target


def _generation_still_authorizes_failure(
    payload: dict[str, object],
    target: Range | Instance,
    expected_operation_id: UUID | str,
) -> bool:
    """Return whether a provider failure still owns the current lifecycle."""
    from engine.launch_intents import authorize_provisioner_payload

    try:
        authorize_provisioner_payload(
            payload,
            target=target,
            expected_operation_id=expected_operation_id,
        )
    except ValueError:
        return False
    return True


def _publish_range_dispatch_failure(payload: dict[str, object], target: Range) -> None:
    """Publish the standard failed status event for a Range dispatch."""
    from engine.models import RangeEventOutbox
    from shared.enums import ResourceStatus
    from shared.messages.events import EVENT_TYPE_STATUS_UPDATED

    event_id = uuid4()
    related_request = target.request
    request_id = str(related_request.request_id) if related_request is not None else str(payload.get("request_id", ""))
    event = {
        "event_type": EVENT_TYPE_STATUS_UPDATED,
        "event_id": str(event_id),
        "timestamp": timezone.now().isoformat(),
        "request_id": request_id,
        "range_id": target.id,
        "user_id": target.user_id,
        "new_status": ResourceStatus.FAILED.value,
        "error_message": PROVISIONER_DISPATCH_FAILED,
    }
    RangeEventOutbox.objects.create(
        event_id=event_id,
        event_type=EVENT_TYPE_STATUS_UPDATED,
        payload=event,
        next_attempt_at=timezone.now(),
    )


def _apply_dispatch_failure(payload: dict[str, object], target: Range | Instance) -> None:
    """Persist the sanitized failure state and its dependent projections."""
    from engine.models import App
    from shared.enums import ResourceStatus

    target.status = ResourceStatus.FAILED.value
    update_fields = ["status", "updated_at"]
    update_fields.extend(clear_provisioner_operation_after_failure(target))
    if isinstance(target, Range):
        target.error_message = PROVISIONER_DISPATCH_FAILED
        update_fields.append("error_message")
    target.save(update_fields=update_fields)
    if isinstance(target, Range):
        from engine.services._receipt import _revoke_receipt_verifier_for_range

        _revoke_receipt_verifier_for_range(target)
        _publish_range_dispatch_failure(payload, target)
    else:
        App.objects.filter(instance=target).update(
            status=ResourceStatus.FAILED.value,
            updated_at=timezone.now(),
        )


def fail_current_provisioner_operation(
    payload: dict[str, object],
    expected_operation_id: UUID | str,
) -> bool:
    """Fail only the domain projection still owned by this operation generation."""
    from engine.launch_intents import command_from_payload

    try:
        command_from_payload(payload)
    except (KeyError, TypeError, ValueError):
        return False
    target = _resolve_failure_target(payload)
    if target is None or not _generation_still_authorizes_failure(payload, target, expected_operation_id):
        return False
    _apply_dispatch_failure(payload, target)
    return True
