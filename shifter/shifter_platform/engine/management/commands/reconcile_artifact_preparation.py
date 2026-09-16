"""Run the dedicated preparation controller independently of message delivery."""

import re
import signal
import tempfile
import threading
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from engine.services import reconcile_preparations

HEARTBEAT = Path(tempfile.gettempdir()) / "worker-preparation-heartbeat"


class Command(BaseCommand):
    """Scan durable operations once or continuously under the controller identity."""

    help = "Reconcile queued artifact preparation and pending cleanup."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--scope-digest", required=True)
        parser.add_argument("--interval", type=int, default=10)
        parser.add_argument("--batch-size", type=int, default=20)

    def handle(self, *args: Any, **options: Any) -> None:
        if not 1 <= options["interval"] <= 60 or not 1 <= options["batch_size"] <= 100:
            raise CommandError("Invalid preparation controller bounds")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", options["scope_digest"]):
            raise CommandError("Invalid preparation scope digest")
        stopped = threading.Event()
        if options["loop"]:
            signal.signal(signal.SIGTERM, lambda *_: stopped.set())
            signal.signal(signal.SIGINT, lambda *_: stopped.set())
        while not stopped.is_set():
            # A wedged provider call must not keep liveness fresh indefinitely.
            # The deployment budget covers the bounded independent readback.
            HEARTBEAT.touch()
            count = reconcile_preparations(limit=options["batch_size"], scope_digest=options["scope_digest"])
            HEARTBEAT.touch()
            self.stdout.write(f"Reconciled {count} artifact preparation operations")
            if not options["loop"]:
                return
            stopped.wait(options["interval"])
