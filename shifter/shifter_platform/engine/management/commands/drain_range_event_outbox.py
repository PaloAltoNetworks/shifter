"""Drain PENDING rows from the range event outbox and publish to the event bus.

Run one-shot (default) or as a continuous loop:

    python manage.py drain_range_event_outbox
    python manage.py drain_range_event_outbox --loop --interval 10

Configuration:
    RANGE_EVENTS_TOPIC_ID (settings or env) — SNS ARN or Pub/Sub topic ID.
    SNS_RANGE_EVENTS_ARN (env fallback) — alias accepted for backward compat.

Concurrency:
    Uses select_for_update(skip_locked=True) inside transaction.atomic() so
    multiple drainer instances can run safely without double-publishing.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
from argparse import ArgumentParser
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from engine.models import OutboxStatus, RangeEventOutbox
from shared.cloud import get_event_bus
from shared.cloud.exceptions import CloudEventBusError

if TYPE_CHECKING:
    from shared.cloud.types import EventBus

logger = logging.getLogger(__name__)

_BACKOFF_BASE_SECONDS = 60
HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "worker-outbox-drainer-heartbeat"
_BACKOFF_CAP_SECONDS = 3600
_MAX_ERROR_LENGTH = 500


def _backoff_seconds(attempts: int) -> int:
    """Exponential backoff with cap.

    Args:
        attempts: The attempt count AFTER incrementing (i.e. 1 on first failure).

    Returns:
        Seconds to wait before the next attempt.
    """
    return min(_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)), _BACKOFF_CAP_SECONDS)


class Command(BaseCommand):
    """Drain PENDING rows from engine_range_event_outbox and publish to the event bus."""

    help = "Drain PENDING range event outbox rows and publish to the configured event bus topic."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Maximum rows to process per drain cycle (default: 100).",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            default=False,
            help="Run continuously, sleeping --interval seconds between cycles.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=10,
            help="Seconds to sleep between loop cycles (default: 10). Ignored without --loop.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        topic_id = self._resolve_topic_id()
        bus = get_event_bus()
        batch_size: int = options["batch_size"]
        loop: bool = options["loop"]
        interval: int = options["interval"]

        logger.info("drain_range_event_outbox: starting batch_size=%d loop=%s", batch_size, loop)
        self.stdout.write(f"Drainer starting: batch_size={batch_size} loop={loop}")

        if loop:
            while True:
                drained = self._drain_batch(bus, topic_id, batch_size)
                self.stdout.write(f"Drained {drained} rows")
                self._touch_heartbeat()
                time.sleep(interval)
        else:
            drained = self._drain_batch(bus, topic_id, batch_size)
            self.stdout.write(f"Drained {drained} rows")

    def _touch_heartbeat(self) -> None:
        """Touch the liveness heartbeat file after each loop iteration."""
        try:
            HEARTBEAT_FILE.touch()
        except OSError:
            logger.warning("Failed to update heartbeat file: %s", HEARTBEAT_FILE)

    def _cleanup_heartbeat(self) -> None:
        """Remove the heartbeat file on graceful shutdown."""
        if HEARTBEAT_FILE.exists():
            with contextlib.suppress(OSError):
                HEARTBEAT_FILE.unlink()

    def _resolve_topic_id(self) -> str:
        """Resolve the event bus topic identifier from settings or environment.

        Fails closed with CommandError if no topic is configured — the drainer
        must not silently discard events when misconfigured.
        """
        topic_id = (
            getattr(settings, "RANGE_EVENTS_TOPIC_ID", None)
            or os.environ.get("RANGE_EVENTS_TOPIC_ID")
            or os.environ.get("SNS_RANGE_EVENTS_ARN")
        )
        if not topic_id:
            raise CommandError(
                "RANGE_EVENTS_TOPIC_ID is not configured. "
                "Set RANGE_EVENTS_TOPIC_ID (or SNS_RANGE_EVENTS_ARN) in the environment. "
                "Drainer cannot publish without a topic."
            )
        return str(topic_id)

    def _drain_batch(self, bus: EventBus, topic_id: str, batch_size: int) -> int:
        """Select and process one bounded batch of due PENDING rows.

        Returns:
            Number of rows processed (published or transitioned to failure/DLQ).
        """
        now = timezone.now()
        with transaction.atomic():
            rows = list(
                RangeEventOutbox.objects.select_for_update(skip_locked=True)
                .filter(status=OutboxStatus.PENDING, next_attempt_at__lte=now)
                .order_by("next_attempt_at")[:batch_size]
            )
            for row in rows:
                self._process_row(bus, topic_id, row)
        return len(rows)

    def _process_row(self, bus: EventBus, topic_id: str, row: RangeEventOutbox) -> None:
        """Publish one outbox row and update its status.

        On success: marks PUBLISHED and sets published_at.
        On CloudEventBusError: increments attempts, applies exponential backoff,
            moves to DLQ when max_attempts is exhausted.

        Payloads are never logged.
        """
        message = json.dumps(row.payload)
        try:
            bus.publish(topic_id, message, attributes={"event_type": row.event_type})
        except CloudEventBusError as exc:
            row.attempts += 1
            row.last_error = str(exc)[:_MAX_ERROR_LENGTH]
            if row.attempts >= row.max_attempts:
                row.status = OutboxStatus.DLQ
                logger.error(
                    "drain_range_event_outbox: DLQ event_id=%s event_type=%s attempts=%d",
                    row.event_id,
                    row.event_type,
                    row.attempts,
                )
            else:
                delay = _backoff_seconds(row.attempts)
                row.next_attempt_at = timezone.now() + timedelta(seconds=delay)
                logger.warning(
                    "drain_range_event_outbox: retry event_id=%s event_type=%s attempts=%d next_in=%ds",
                    row.event_id,
                    row.event_type,
                    row.attempts,
                    delay,
                )
            row.save(update_fields=["status", "attempts", "last_error", "next_attempt_at"])
            return

        row.status = OutboxStatus.PUBLISHED
        row.published_at = timezone.now()
        row.save(update_fields=["status", "published_at"])
        logger.info(
            "drain_range_event_outbox: published event_id=%s event_type=%s",
            row.event_id,
            row.event_type,
        )
