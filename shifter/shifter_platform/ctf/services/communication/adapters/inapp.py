"""In-app channel adapter (#2098).

The in-app channel's durable record is the ``RecipientSnapshot`` / ``ParticipantReceipt``
committed at admission -- inbox availability never depends on this adapter. The
adapter only publishes a reference-only WebSocket wake-up (an accelerator) keyed on
the stable per-recipient snapshot identity, so a socket outage, reconnect, or worker
retry can never undo availability or duplicate a visible inbox entry.

It receives identifiers only (never the email coordinate or decrypted body) and
returns a closed outcome. A recipient without an account has nothing to wake, which
is an accepted no-op, not a failure.
"""

from __future__ import annotations

import logging

from ctf.enums_communication import CommunicationChannel

from .contract import DeliveryCommand, DeliveryOutcome, OutcomeClass

logger = logging.getLogger(__name__)


class InAppAdapter:
    """Reference-only WebSocket wake-up over the durable in-app inbox."""

    channel = CommunicationChannel.IN_APP.value

    def deliver(self, command: DeliveryCommand, *, timeout: float) -> DeliveryOutcome:
        """Publish a reference-only wake-up for one recipient snapshot.

        Availability is already durable, so a failed publish is retriable (clients
        still see the entry on reconnect/poll) rather than a delivery failure. The
        ``timeout`` is part of the shared adapter contract; the in-app wake-up is a
        fast local publish, so it is only an upper sanity bound recorded for
        observability here.
        """
        from ctf.services.notification.realtime import publish_communication_wakeup

        logger.debug("in-app %s wake-up for snapshot %s (timeout=%ss)", self.channel, command.snapshot_id, timeout)
        if command.recipient_user_id is None:
            # No account to wake; the durable inbox entry is the record of truth.
            return DeliveryOutcome(OutcomeClass.ACCEPTED, reason="no_socket_recipient")
        try:
            published = publish_communication_wakeup(
                event_id=command.event_id,
                recipient_user_id=command.recipient_user_id,
                snapshot_id=command.snapshot_id,
                references={
                    "snapshot_id": str(command.snapshot_id),
                    "intent_id": str(command.intent_id),
                },
            )
        except Exception:
            # Bounded: a wake-up failure never affects durable availability.
            logger.warning("in-app wake-up publish failed for snapshot %s", command.snapshot_id)
            return DeliveryOutcome(OutcomeClass.RETRIABLE, reason="wakeup_publish_error")
        reason = "wakeup_published" if published else "wakeup_unavailable"
        outcome = OutcomeClass.ACCEPTED if published else OutcomeClass.RETRIABLE
        return DeliveryOutcome(outcome, reason=reason)
