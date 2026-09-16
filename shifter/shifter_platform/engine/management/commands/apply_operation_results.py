"""Apply pending provisioner operation results from the result inbox.

Runs the Engine-owned applier: it claims PENDING ``OperationResultInbox`` rows,
validates their operation contracts, and applies cut-over families to domain
state, audit, and the range event outbox in one transaction. Compatibility
families without a declared step contract receive a validation-only shadow
disposition. Deployed as a portal worker (under the portal runtime role, not the
provisioner) alongside the other management-command workers.
"""

from __future__ import annotations

import contextlib
import logging
import tempfile
import time
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from engine.services import apply_pending_operation_results

logger = logging.getLogger(__name__)
HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "worker-operation-result-applier-heartbeat"


class Command(BaseCommand):
    """Evaluate due operation-result inbox rows while maintaining worker liveness."""

    help = "Apply pending provisioner operation results through the Engine-owned applier."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Register batch and polling options for the applier worker."""
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--loop", action="store_true", default=False)
        parser.add_argument("--interval", type=int, default=10)

    def handle(self, *args: Any, **options: Any) -> None:
        """Apply once or continuously according to the command options."""
        while True:
            self._touch_heartbeat()
            evaluated = apply_pending_operation_results(batch_size=options["batch_size"])
            self.stdout.write(f"Evaluated {evaluated} operation results")
            if not options["loop"]:
                return
            time.sleep(options["interval"])

    @staticmethod
    def _touch_heartbeat() -> None:
        """Refresh the applier liveness marker when the filesystem permits."""
        with contextlib.suppress(OSError):
            HEARTBEAT_FILE.touch()
