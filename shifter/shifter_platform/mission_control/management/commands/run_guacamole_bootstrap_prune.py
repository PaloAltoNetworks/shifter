"""Guacamole bootstrap pruning service.

Periodically deletes expired ``GuacamoleBootstrapRequest`` rows so abandoned
Guacamole session token URLs do not persist at rest and the table does not
grow unbounded. Pruning is the backstop control; the immediate control is
clearing the token URL on delivery (see ``mission_control.guacamole_bootstrap``).

Follows the same signal-handling and heartbeat pattern as
``ctf/management/commands/run_ctf_scheduler.py`` and
``shared/management/commands/run_worker.py``.

Usage:
    python manage.py run_guacamole_bootstrap_prune
    python manage.py run_guacamole_bootstrap_prune --poll-interval 30 --batch-size 200

Health monitoring:
    Touches /tmp/guacamole-bootstrap-prune-heartbeat after each poll cycle.
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

from mission_control.guacamole_bootstrap import prune_expired_bootstrap_requests

logger = logging.getLogger(__name__)

HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "guacamole-bootstrap-prune-heartbeat"

_DEFAULT_POLL_INTERVAL = 60
_DEFAULT_BATCH_SIZE = 500


class Command(BaseCommand):
    """Run the Guacamole bootstrap pruning loop."""

    help = "Delete expired Guacamole bootstrap rows on a schedule"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.shutdown = False

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--poll-interval",
            type=int,
            default=int(getattr(settings, "GUACAMOLE_BOOTSTRAP_PRUNE_INTERVAL_SECONDS", _DEFAULT_POLL_INTERVAL)),
            help="Seconds between prune cycles",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=int(getattr(settings, "GUACAMOLE_BOOTSTRAP_PRUNE_BATCH_SIZE", _DEFAULT_BATCH_SIZE)),
            help="Max rows deleted per batch",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        poll_interval = max(1, options["poll_interval"])
        batch_size = max(1, options["batch_size"])

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        logger.info(
            "Guacamole bootstrap prune starting: poll_interval=%ds batch_size=%d",
            poll_interval,
            batch_size,
        )

        while not self.shutdown:
            try:
                self._prune_cycle(batch_size)
            except Exception:
                logger.exception("Error in Guacamole bootstrap prune cycle")
            finally:
                close_old_connections()

            self._touch_heartbeat()

            # Sleep in short increments so we respond to signals quickly.
            for _ in range(poll_interval):
                if self.shutdown:
                    break
                time.sleep(1)

        self._cleanup_heartbeat()
        logger.info("Guacamole bootstrap prune shutdown complete")

    def _prune_cycle(self, batch_size: int) -> int:
        """Drain expired rows in bounded batches; return the total deleted."""
        total = 0
        while not self.shutdown:
            deleted = prune_expired_bootstrap_requests(batch_size=batch_size)
            total += deleted
            if deleted < batch_size:
                break
        if total:
            logger.info("Pruned %d expired Guacamole bootstrap row(s)", total)
        return total

    def _signal_handler(self, signum: int, frame: FrameType | None) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Guacamole bootstrap prune received %s, shutting down", sig_name)
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
