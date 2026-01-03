"""SQS worker management command.

Replaces Celery workers with direct SQS polling using boto3.
Run one instance per queue:

    python manage.py run_worker --queue cms
    python manage.py run_worker --queue engine
    python manage.py run_worker --queue mc

Health monitoring:
    The worker touches a heartbeat file after each poll cycle.
    Docker HEALTHCHECK can monitor this file to detect hung workers.
    Heartbeat file: /tmp/worker-{queue}-heartbeat
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import boto3
from django.conf import settings
from django.core.management.base import BaseCommand

from cms.handlers import process_range_event as cms_handler
from engine.handlers import process_range_event as engine_handler
from mission_control.handlers import process_range_event as mc_handler

logger = logging.getLogger(__name__)

# Heartbeat file location - Docker HEALTHCHECK monitors this
HEARTBEAT_DIR = Path(tempfile.gettempdir())

QUEUE_CONFIG: dict[str, dict] = {
    "cms": {
        "url_env": "SQS_CMS_URL",
        "handler": cms_handler,
    },
    "engine": {
        "url_env": "SQS_ENGINE_URL",
        "handler": engine_handler,
    },
    "mc": {
        "url_env": "SQS_MC_URL",
        "handler": mc_handler,
    },
}


class Command(BaseCommand):
    """SQS worker that polls a queue and dispatches to handlers."""

    help = "Run SQS worker for a specific queue (cms, engine, or mc)"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shutdown = False
        self.sqs = None
        self.heartbeat_file: Path | None = None
        self.queue_name: str = ""

    def add_arguments(self, parser):
        parser.add_argument(
            "--queue",
            type=str,
            choices=["cms", "engine", "mc"],
            required=True,
            help="Queue to consume from: cms, engine, or mc",
        )
        parser.add_argument(
            "--wait-time",
            type=int,
            default=20,
            help="SQS long polling wait time in seconds (default: 20)",
        )
        parser.add_argument(
            "--max-messages",
            type=int,
            default=10,
            help="Max messages to receive per poll (default: 10)",
        )

    def handle(self, *args, **options):
        self.queue_name = options["queue"]
        wait_time = options["wait_time"]
        max_messages = options["max_messages"]

        config = QUEUE_CONFIG[self.queue_name]
        queue_url = os.environ.get(config["url_env"], "")
        handler: Callable = config["handler"]

        if not queue_url:
            self.stderr.write(self.style.ERROR(f"Environment variable {config['url_env']} not set"))
            sys.exit(1)

        # Set up heartbeat file for health monitoring
        self.heartbeat_file = HEARTBEAT_DIR / f"worker-{self.queue_name}-heartbeat"
        self._check_restart_indicator()

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        self.sqs = boto3.client("sqs", region_name=settings.AWS_REGION)

        # Log startup with structured fields for CloudWatch filtering
        logger.info(
            "Worker starting: queue=%s url=%s wait_time=%ds max_messages=%d",
            self.queue_name,
            queue_url,
            wait_time,
            max_messages,
        )

        self._poll_loop(queue_url, handler, wait_time, max_messages)

        # Clean up heartbeat file on graceful shutdown
        self._cleanup_heartbeat()
        logger.info("Worker shutdown complete: queue=%s", self.queue_name)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, shutting down: queue=%s", sig_name, self.queue_name)
        self.shutdown = True

    def _check_restart_indicator(self):
        """Check if heartbeat file exists from a previous run (indicates restart)."""
        if self.heartbeat_file and self.heartbeat_file.exists():
            # Stale heartbeat file means we're restarting after a crash/kill
            try:
                mtime = self.heartbeat_file.stat().st_mtime
                age_seconds = time.time() - mtime
                logger.warning(
                    "Worker restart detected: queue=%s previous_heartbeat_age=%.1fs",
                    self.queue_name,
                    age_seconds,
                )
            except OSError:
                logger.warning(
                    "Worker restart detected: queue=%s (could not read previous heartbeat)",
                    self.queue_name,
                )

    def _touch_heartbeat(self):
        """Update heartbeat file timestamp for health monitoring."""
        if self.heartbeat_file:
            try:
                self.heartbeat_file.touch()
            except OSError:
                logger.warning("Failed to update heartbeat file: %s", self.heartbeat_file)

    def _cleanup_heartbeat(self):
        """Remove heartbeat file on graceful shutdown."""
        if self.heartbeat_file and self.heartbeat_file.exists():
            with contextlib.suppress(OSError):
                self.heartbeat_file.unlink()

    def _poll_loop(
        self,
        queue_url: str,
        handler: Callable,
        wait_time: int,
        max_messages: int,
    ):
        """Main polling loop."""
        while not self.shutdown:
            try:
                response = self.sqs.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=max_messages,
                    WaitTimeSeconds=wait_time,
                    AttributeNames=["All"],
                    MessageAttributeNames=["All"],
                )

                # Update heartbeat after successful poll (even if no messages)
                self._touch_heartbeat()

                messages = response.get("Messages", [])

                for message in messages:
                    if self.shutdown:
                        break

                    self._process_message(queue_url, handler, message)

            except Exception:
                logger.exception("Error polling SQS queue: queue=%s", self.queue_name)
                if not self.shutdown:
                    time.sleep(5)

    def _process_message(
        self,
        queue_url: str,
        handler: Callable,
        message: dict,
    ):
        """Process a single SQS message."""
        receipt_handle = message["ReceiptHandle"]
        body = message["Body"]

        try:
            handler(body)

            self.sqs.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
            )

        except Exception:
            logger.exception("Error processing message: %s", message.get("MessageId"))
