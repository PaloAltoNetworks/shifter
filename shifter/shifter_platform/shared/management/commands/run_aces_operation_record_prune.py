"""ACES operation-record pruning service.

Periodically deletes ``AcesOperationRecord`` rows past their
``retention_expires_at`` boundary so runtime snapshots and adjacent operation
records stay bounded operational observations rather than an ever-growing
archive. Redaction is enforced at write time (``shared.schemas.aces_operation``);
this service is the retention backstop, not a redaction control.

Follows the same signal-handling and heartbeat pattern as
``mission_control/management/commands/run_guacamole_bootstrap_prune.py`` and
``shared/management/commands/run_worker.py``.

Usage:
    python manage.py run_aces_operation_record_prune
    python manage.py run_aces_operation_record_prune --poll-interval 3600 --batch-size 200

Health monitoring:
    Touches /tmp/aces-operation-record-prune-heartbeat after each poll cycle.
"""

from __future__ import annotations

import contextlib
import logging
import signal
import tempfile
import time
from argparse import ArgumentParser
from pathlib import Path
from types import FrameType
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from shared.aces.operations import prune_expired_aces_operation_records

logger = logging.getLogger(__name__)

HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "aces-operation-record-prune-heartbeat"

_DEFAULT_POLL_INTERVAL = 3600
_DEFAULT_BATCH_SIZE = 500
# Upper bound on delete work per poll cycle: a cold deploy or a retention-policy
# change can leave a large expired backlog, and draining it all in one cycle
# would run unbounded DB work and starve the liveness heartbeat. Each cycle
# deletes at most _MAX_BATCHES_PER_CYCLE * batch_size rows; the remainder drains
# on subsequent cycles. The heartbeat is refreshed after every batch so the
# liveness probe never kills the worker mid-drain.
_MAX_BATCHES_PER_CYCLE = 50


class Command(BaseCommand):
    """Run the ACES operation-record pruning loop."""

    help = "Delete expired ACES operation sidecar rows on a schedule"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.shutdown = False

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--poll-interval",
            type=int,
            default=int(getattr(settings, "ACES_OPERATION_RECORD_PRUNE_INTERVAL_SECONDS", _DEFAULT_POLL_INTERVAL)),
            help="Seconds between prune cycles",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=int(getattr(settings, "ACES_OPERATION_RECORD_PRUNE_BATCH_SIZE", _DEFAULT_BATCH_SIZE)),
            help="Max rows deleted per batch",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        poll_interval = max(1, options["poll_interval"])
        batch_size = max(1, options["batch_size"])

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        logger.info(
            "ACES operation-record prune starting: poll_interval=%ds batch_size=%d",
            poll_interval,
            batch_size,
        )

        while not self.shutdown:
            try:
                self._prune_cycle(batch_size)
            except Exception:
                logger.exception("Error in ACES operation-record prune cycle")
            finally:
                close_old_connections()

            self._touch_heartbeat()

            # Sleep in short increments so we respond to signals quickly.
            for _ in range(poll_interval):
                if self.shutdown:
                    break
                time.sleep(1)

        self._cleanup_heartbeat()
        logger.info("ACES operation-record prune shutdown complete")

    def _prune_cycle(self, batch_size: int) -> int:
        """Delete expired rows in bounded batches; return the total deleted.

        Bounded to at most ``_MAX_BATCHES_PER_CYCLE`` batches per cycle so a large
        expired backlog cannot run unbounded delete work in one poll; the
        heartbeat is refreshed after each batch so the liveness probe cannot kill
        the worker mid-drain. Any remaining backlog drains on the next cycle.
        """
        total = 0
        for _ in range(_MAX_BATCHES_PER_CYCLE):
            if self.shutdown:
                break
            deleted = prune_expired_aces_operation_records(batch_size=batch_size)
            total += deleted
            self._touch_heartbeat()
            if deleted < batch_size:
                break
        if total:
            logger.info("Pruned %d expired ACES operation record(s)", total)
        return total

    def _signal_handler(self, signum: int, frame: FrameType | None) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("ACES operation-record prune received %s, shutting down", sig_name)
        self.shutdown = True

    def _touch_heartbeat(self) -> None:
        try:
            HEARTBEAT_FILE.touch()
        except OSError:
            logger.warning("Failed to update heartbeat file: %s", HEARTBEAT_FILE)

    def _cleanup_heartbeat(self) -> None:
        if HEARTBEAT_FILE.exists():
            with contextlib.suppress(OSError):
                HEARTBEAT_FILE.unlink()
