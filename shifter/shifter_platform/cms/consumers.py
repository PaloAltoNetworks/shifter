"""Channel consumers for CMS app.

These consumers handle asynchronous events from the Engine provisioner
via Redis pub/sub, updating CMS's view of range state.
"""

from __future__ import annotations

import logging

from channels.consumer import SyncConsumer
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class CMSRangeStatusConsumer(SyncConsumer):
    """Listens for range status updates from Engine provisioner.

    Updates RangeInstance.status when status change events are received.
    This consumer runs as a Django Channels worker process.

    Message format: See shared.messages.events.RangeStatusUpdatedEvent

    Error handling:
        - Validation failure: logs error, returns early
        - RangeInstance not found: logs warning, returns early
        - user_id mismatch: logs error, returns early
        - Database error: logs exception, returns early (see GH #455)
    """

    def range_status(self, message: dict) -> None:
        """Handle range status update event.

        Validates message using Pydantic, updates RangeInstance.status,
        and logs outcomes.

        Args:
            message: Dict containing range_id, new_status, old_status, user_id.

        Returns:
            None. Errors are logged and handled gracefully.
        """
        from cms.models import RangeInstance
        from shared.messages.events import RangeStatusUpdatedEvent

        logger.debug("CMS consumer received message: %s", message)

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
        # Fetch and validate RangeInstance
        # =====================================================================

        try:
            instance = RangeInstance.objects.get(range_id=event.range_id)
        except RangeInstance.DoesNotExist:
            logger.warning(
                "RangeInstance not found: range_id=%s user_id=%s",
                event.range_id,
                event.user_id,
            )
            return

        # Verify user_id matches (defensive check against corrupted messages)
        if instance.user_id != event.user_id:
            logger.error(
                "user_id mismatch: message user_id=%s, instance user_id=%s (range_id=%s)",
                event.user_id,
                instance.user_id,
                event.range_id,
            )
            return

        # Log current state for debugging
        logger.debug(
            "Found RangeInstance: range_id=%s current_status=%s deleted_at=%s",
            event.range_id,
            instance.status,
            instance.deleted_at,
        )

        # Verify old_status matches current state (detect race conditions)
        if instance.status != event.old_status.value:
            logger.warning(
                "Status mismatch: expected old_status=%s, found current=%s "
                "(range_id=%s). Proceeding with update anyway.",
                event.old_status.value,
                instance.status,
                event.range_id,
            )

        # =====================================================================
        # Update status
        # =====================================================================

        previous_status = instance.status
        instance.status = event.new_status.value

        try:
            instance.save(update_fields=["status"])
        except Exception:
            logger.exception(
                "Database error saving RangeInstance: range_id=%s status=%s",
                event.range_id,
                event.new_status.value,
            )
            return  # Message dropped; see GH issue #455 for recovery options

        logger.info(
            "CMS updated RangeInstance: range_id=%s status=%s->%s user_id=%s",
            event.range_id,
            previous_status,
            event.new_status.value,
            event.user_id,
        )

        # Log if this was a terminal status (deleted_at will be set by model)
        if instance.deleted_at is not None:
            logger.debug(
                "RangeInstance marked as deleted: range_id=%s deleted_at=%s",
                event.range_id,
                instance.deleted_at,
            )
