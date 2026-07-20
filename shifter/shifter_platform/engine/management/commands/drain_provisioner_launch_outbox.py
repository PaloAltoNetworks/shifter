"""Drain validated launch intents from the dedicated privileged worker."""

from __future__ import annotations

import contextlib
import logging
import tempfile
import threading
import time
from argparse import ArgumentParser
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from engine.launch_intents import (
    authorize_provisioner_payload,
    command_from_payload,
    fail_current_provisioner_operation,
)
from engine.models import ProvisionerLaunchIntent, ProvisionerLaunchStatus

logger = logging.getLogger(__name__)
HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "worker-provisioner-launcher-heartbeat"
HEARTBEAT_INTERVAL_SECONDS = 30


class Command(BaseCommand):
    """Drain due launch intents while maintaining worker liveness."""

    help = "Launch due provisioner intents from the dedicated launcher identity."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Register batch and polling options for the launcher worker."""
        parser.add_argument("--batch-size", type=int, default=20)
        parser.add_argument("--loop", action="store_true", default=False)
        parser.add_argument("--interval", type=int, default=10)

    def handle(self, *args: Any, **options: Any) -> None:
        """Drain once or continuously according to the command options."""
        while True:
            self._touch_heartbeat()
            drained = self._drain_batch(options["batch_size"])
            self.stdout.write(f"Drained {drained} launch intents")
            if not options["loop"]:
                return
            time.sleep(options["interval"])

    @staticmethod
    def _touch_heartbeat() -> None:
        """Refresh the launcher liveness marker when the filesystem permits."""
        with contextlib.suppress(OSError):
            HEARTBEAT_FILE.touch()

    @contextlib.contextmanager
    def _active_heartbeat(self) -> Iterator[None]:
        """Keep liveness fresh while a bounded provider reconciliation runs."""
        stopped = threading.Event()

        def heartbeat_loop() -> None:
            """Refresh liveness until the active provider call completes."""
            while not stopped.wait(HEARTBEAT_INTERVAL_SECONDS):
                self._touch_heartbeat()

        self._touch_heartbeat()
        thread = threading.Thread(
            target=heartbeat_loop,
            name="provisioner-launcher-heartbeat",
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(timeout=1)
            self._touch_heartbeat()

    def _drain_batch(self, batch_size: int) -> int:
        drained = 0
        for _ in range(batch_size):
            row = self._claim_next()
            if row is None:
                break
            with self._active_heartbeat():
                self._launch(row)
            drained += 1
        return drained

    @staticmethod
    def _claim_next() -> ProvisionerLaunchIntent | None:
        with transaction.atomic():
            row = (
                ProvisionerLaunchIntent.objects.select_for_update(skip_locked=True)
                .filter(
                    Q(status=ProvisionerLaunchStatus.PENDING) | Q(status=ProvisionerLaunchStatus.RUNNING),
                    next_attempt_at__lte=timezone.now(),
                )
                .order_by("next_attempt_at")
                .first()
            )
            if row is None:
                return None
            row.status = ProvisionerLaunchStatus.RUNNING
            row.next_attempt_at = timezone.now() + timedelta(minutes=5)
            row.save(update_fields=["status", "next_attempt_at"])
            return row

    def _launch(self, row: ProvisionerLaunchIntent) -> None:
        from engine.ecs import dispatch_provisioner_command

        try:
            command = command_from_payload(row.payload)
            # Lock the domain projection while validating the operation generation.
            # This linearizes a stale launch against a concurrent lifecycle transition:
            # either this generation is authorized first, or the newer generation wins
            # and this intent is rejected before provider dispatch.
            with transaction.atomic():
                authorize_provisioner_payload(row.payload, expected_operation_id=row.operation_id)
                task_ref = dispatch_provisioner_command(command, task_identity=str(row.intent_id))
            if not task_ref:
                raise RuntimeError("provisioner task runner is not configured")
        except Exception as exc:
            self._record_failure(row, exc)
            return
        self._record_success(row, task_ref)

    @staticmethod
    def _lease_matches(current: ProvisionerLaunchIntent, claimed: ProvisionerLaunchIntent) -> bool:
        """Fence a worker whose RUNNING lease was reclaimed while it was dispatching."""
        return current.status == ProvisionerLaunchStatus.RUNNING and current.next_attempt_at == claimed.next_attempt_at

    def _record_failure(self, row: ProvisionerLaunchIntent, exc: Exception) -> None:
        with transaction.atomic():
            current = ProvisionerLaunchIntent.objects.select_for_update().get(pk=row.pk)
            if not self._lease_matches(current, row):
                logger.info("ignoring stale provisioner launch failure intent_id=%s", row.intent_id)
                return
            current.attempts += 1
            current.last_error = type(exc).__name__[:128]
            if current.attempts >= current.max_attempts:
                current.status = ProvisionerLaunchStatus.DLQ
                fail_current_provisioner_operation(current.payload, current.operation_id)
            else:
                current.status = ProvisionerLaunchStatus.PENDING
                current.next_attempt_at = timezone.now() + timedelta(
                    seconds=min(60 * 2 ** (current.attempts - 1), 3600)
                )
            current.save(update_fields=["status", "attempts", "last_error", "next_attempt_at"])
        logger.warning(
            "provisioner launch failed intent_id=%s error_type=%s",
            current.intent_id,
            current.last_error,
        )

    def _record_success(self, row: ProvisionerLaunchIntent, task_ref: str) -> None:
        with transaction.atomic():
            current = ProvisionerLaunchIntent.objects.select_for_update().get(pk=row.pk)
            if not self._lease_matches(current, row):
                logger.info("ignoring stale provisioner launch success intent_id=%s", row.intent_id)
                return
            current.status = ProvisionerLaunchStatus.SUCCEEDED
            current.task_ref = task_ref
            current.last_error = ""
            current.launched_at = timezone.now()
            current.save(update_fields=["status", "task_ref", "last_error", "launched_at"])
