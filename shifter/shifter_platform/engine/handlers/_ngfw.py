"""NGFW lifecycle notification handler (audit/log only).

The provisioner writes all NGFW state directly to the database; this handler is
a notification consumer that records an audit trail. Split out of
``engine/handlers.py`` (#685).
"""

from __future__ import annotations

import logging

from shared.audit import AuditAction, AuditEntityType, AuditTarget, StateChange, audit_log_system_event
from shared.messages.payloads import NGFWEventPayload

from ._audit import _status_to_action

# Stable "engine.handlers" logger namespace (conftest propagation list, audit
# source parity) even though this code now lives in a package submodule.
logger = logging.getLogger("engine.handlers")


def _handle_ngfw_event(event: NGFWEventPayload) -> None:
    """Handle NGFW event notification - log only, no DB updates.

    The provisioner writes all state directly to the database.
    This handler serves as:
    - Audit trail for NGFW lifecycle events
    - Notification consumer for other services (MC, CMS)

    Args:
        event: Event payload with request_id, instance_id, app_id, status.
    """
    event_id = event.get("event_id", "unknown")
    request_id = event.get("request_id")
    instance_id = event.get("instance_id")
    app_id = event.get("app_id")
    status = event.get("status")

    # NGFWs use opaque UUID identities, so retain the integer sentinel and bind
    # the durable audit target to the application UUID.
    audit_log_system_event(
        AuditTarget(AuditEntityType.NGFW, 0, str(app_id or instance_id or event_id)),
        action=_status_to_action(status) if status else AuditAction.UPDATE,
        source="engine.handlers",
        state=StateChange(
            new={
                "status": status,
                "instance_id": instance_id,
                "app_id": app_id,
            }
        ),
        request_id=str(request_id) if request_id else event_id,
    )

    # Log the event for audit purposes
    logger.info(
        "Engine received NGFW event: request_id=%s instance_id=%s app_id=%s status=%s event_id=%s",
        request_id,
        instance_id,
        app_id,
        status,
        event_id,
    )
