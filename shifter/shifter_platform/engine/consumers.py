"""Channel consumers for Engine app.

These consumers handle asynchronous events from the Engine provisioner
via Redis pub/sub, updating Engine's internal Range model state.
"""

from __future__ import annotations

import logging

from channels.consumer import SyncConsumer
from django.utils import timezone
from pydantic import ValidationError

from shared.enums import RangeStatus

logger = logging.getLogger(__name__)


class EngineRangeStatusConsumer(SyncConsumer):
    """Listens for range status updates from Engine provisioner.

    Updates Range.status when status change events are received.
    This consumer runs as a Django Channels worker process.

    Message format: See shared.messages.events.RangeStatusUpdatedEvent

    Error handling:
        - Validation failure: logs error, returns early
        - Range not found: logs warning, returns early
        - user_id mismatch: logs error, returns early
        - Database error: logs exception, returns early (see GH #455)
    """

    def range_status(self, message: dict) -> None:
        """Handle range status update event.

        Validates message using Pydantic, updates Range.status and related
        timestamp fields, and logs outcomes.

        Args:
            message: Dict containing range_id, new_status, old_status, user_id.

        Returns:
            None. Errors are logged and handled gracefully.
        """
        from engine.models import Range
        from shared.messages.events import RangeStatusUpdatedEvent

        logger.debug("Engine consumer received message: %s", message)

        # =====================================================================
        # Validate message using Pydantic contract
        # =====================================================================

        try:
            event = RangeStatusUpdatedEvent(**message)
        except TypeError as e:
            logger.error(
                "Invalid message format: %s (message=%s)",
                str(e),
                message,
            )
            return
        except ValidationError as e:
            logger.error(
                "Invalid message format: %s (message=%s)",
                e.errors(),
                message,
            )
            return

        logger.debug(
            "Validated status update: range_id=%s old=%s new=%s user_id=%s",
            event.range_id,
            event.old_status.value,
            event.new_status.value,
            event.user_id,
        )

        # =====================================================================
        # Fetch and validate Range
        # =====================================================================

        try:
            range_obj = Range.objects.get(id=event.range_id)
        except Range.DoesNotExist:
            logger.warning(
                "Range not found: range_id=%s user_id=%s",
                event.range_id,
                event.user_id,
            )
            return

        # Verify user_id matches (defensive check against corrupted messages)
        if range_obj.user_id != event.user_id:
            logger.error(
                "user_id mismatch: message user_id=%s, range user_id=%s (range_id=%s)",
                event.user_id,
                range_obj.user_id,
                event.range_id,
            )
            return

        # Log current state for debugging
        logger.debug(
            "Found Range: range_id=%s current_status=%s",
            event.range_id,
            range_obj.status,
        )

        # Verify old_status matches current state (detect race conditions)
        if range_obj.status != event.old_status.value:
            logger.warning(
                "Status mismatch: expected old_status=%s, found current=%s "
                "(range_id=%s). Proceeding with update anyway.",
                event.old_status.value,
                range_obj.status,
                event.range_id,
            )

        # =====================================================================
        # Update status and related fields
        # =====================================================================

        previous_status = range_obj.status
        range_obj.status = event.new_status.value
        update_fields = ["status"]

        # Set ready_at when transitioning to READY
        if event.new_status == RangeStatus.READY:
            range_obj.ready_at = timezone.now()
            update_fields.append("ready_at")

        # Store error message on failure
        if event.new_status == RangeStatus.FAILED and event.error_message:
            range_obj.error_message = event.error_message
            update_fields.append("error_message")

        # Set destroyed_at when transitioning to DESTROYED
        if event.new_status == RangeStatus.DESTROYED:
            range_obj.destroyed_at = timezone.now()
            update_fields.append("destroyed_at")

        try:
            range_obj.save(update_fields=update_fields)
        except Exception:
            logger.exception(
                "Database error saving Range: range_id=%s status=%s",
                event.range_id,
                event.new_status.value,
            )
            return  # Message dropped; see GH issue #455 for recovery options

        logger.info(
            "Engine updated Range: range_id=%s status=%s->%s user_id=%s",
            event.range_id,
            previous_status,
            event.new_status.value,
            event.user_id,
        )
