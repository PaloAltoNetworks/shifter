"""Prune expired, verified-resolved public-operation retry bindings (#2086, ADR-063-R5).

Single-shot, bounded pruning invoked on a schedule (e.g. a Kubernetes CronJob). It
deletes retry bindings only when their retention window has elapsed AND the bound
operation's cleanup is verified absent by scoped provider inventory/readback
evidence, so the table stays bounded without ever deleting the recovery/residual
evidence of an unresolved operation.

Usage:
    python manage.py prune_retry_bindings
    python manage.py prune_retry_bindings --batch-size 200
"""

from __future__ import annotations

import logging
from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from engine.retry_binding import prune_expired_retry_bindings

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 500
# Bound the delete work per invocation so a large expired backlog drains across
# scheduled runs rather than one unbounded query.
_MAX_BATCHES = 50


class Command(BaseCommand):
    """Delete expired retry bindings whose operation cleanup is verified absent."""

    help = "Prune expired, inventory-verified public-operation retry bindings"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=int(getattr(settings, "RETRY_BINDING_PRUNE_BATCH_SIZE", _DEFAULT_BATCH_SIZE)),
            help="Max bindings deleted per batch",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size = max(1, options["batch_size"])
        total = 0
        for _ in range(_MAX_BATCHES):
            deleted = prune_expired_retry_bindings(batch_size=batch_size)
            total += deleted
            if deleted < batch_size:
                break
        logger.info("Pruned %d expired verified-resolved retry binding(s)", total)
        self.stdout.write(f"Pruned {total} retry binding(s)")
