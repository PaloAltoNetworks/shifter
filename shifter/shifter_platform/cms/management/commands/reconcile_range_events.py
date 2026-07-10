"""Reconcile stale CMS projection rows against authoritative engine state.

Scans for CMS ``RangeInstance`` rows whose status has not advanced despite the
corresponding authoritative ``engine.Range`` having moved forward. When drift
is found the reconciler re-drives the same domain transition the live event
would have triggered.

Operational characteristics:
- One-shot by default (process a bounded batch and exit), suitable for a
  Kubernetes CronJob or AWS scheduled task.
- Optional ``--loop`` mode for persistent deployments.
- Uses ``select_for_update(skip_locked=True)`` to be safe under concurrent
  reconciler instances without blocking.
- Emits WARNING-level log lines whenever drift is detected, giving operators
  an observable signal for lost-event recovery.
- Never logs payloads, secrets, or raw exception reprs (uses safe_log_id /
  safe_log_value from the shared sanitiser).
"""

from __future__ import annotations

import contextlib
import logging
import tempfile
import time
from argparse import ArgumentParser
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from cms.handlers.range_events import apply_range_status
from cms.models import RangeInstance
from engine.services import get_authoritative_range_status
from shared.enums import TERMINAL_STATUSES, ResourceStatus
from shared.log_sanitize import safe_log_id

logger = logging.getLogger(__name__)

HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "worker-reconciler-heartbeat"

# ---------------------------------------------------------------------------
# Status recovery relation (which lost transitions the reconciler may repair)
# ---------------------------------------------------------------------------

# The range lifecycle is NOT a single increasing ordinal: a range can be PAUSED
# and then RESUME back to READY. A linear rank wrongly classifies the
# paused/resuming → ready recovery (the lost resume event the reconciler exists
# to repair) as a backward move. Instead we model the legitimate recoveries
# explicitly: for each current CMS status, the set of authoritative engine
# statuses the reconciler may converge it to. Terminal statuses (FAILED,
# DESTROYED) are absorbing — once CMS is terminal the reconciler never moves it,
# so a stale/racy engine read cannot resurrect a finished range. Backward
# regressions (e.g. READY → PROVISIONING) are intentionally absent; the engine
# emits its own forward events for any genuine re-provision.
_RECOVERY_TRANSITIONS: dict[str, frozenset[str]] = {
    ResourceStatus.PENDING.value: frozenset(
        {
            ResourceStatus.PROVISIONING.value,
            ResourceStatus.READY.value,
            ResourceStatus.PAUSING.value,
            ResourceStatus.PAUSED.value,
            ResourceStatus.RESUMING.value,
            ResourceStatus.DESTROYING.value,
            ResourceStatus.DESTROYED.value,
            ResourceStatus.FAILED.value,
        }
    ),
    ResourceStatus.PROVISIONING.value: frozenset(
        {
            ResourceStatus.READY.value,
            ResourceStatus.PAUSING.value,
            ResourceStatus.PAUSED.value,
            ResourceStatus.RESUMING.value,
            ResourceStatus.DESTROYING.value,
            ResourceStatus.DESTROYED.value,
            ResourceStatus.FAILED.value,
        }
    ),
    ResourceStatus.READY.value: frozenset(
        {
            ResourceStatus.PAUSING.value,
            ResourceStatus.PAUSED.value,
            ResourceStatus.RESUMING.value,
            ResourceStatus.DESTROYING.value,
            ResourceStatus.DESTROYED.value,
            ResourceStatus.FAILED.value,
        }
    ),
    ResourceStatus.PAUSING.value: frozenset(
        {
            ResourceStatus.PAUSED.value,
            ResourceStatus.RESUMING.value,
            ResourceStatus.READY.value,
            ResourceStatus.DESTROYING.value,
            ResourceStatus.DESTROYED.value,
            ResourceStatus.FAILED.value,
        }
    ),
    ResourceStatus.PAUSED.value: frozenset(
        {
            ResourceStatus.RESUMING.value,
            ResourceStatus.READY.value,
            ResourceStatus.DESTROYING.value,
            ResourceStatus.DESTROYED.value,
            ResourceStatus.FAILED.value,
        }
    ),
    ResourceStatus.RESUMING.value: frozenset(
        {
            ResourceStatus.READY.value,
            ResourceStatus.PAUSING.value,
            ResourceStatus.PAUSED.value,
            ResourceStatus.DESTROYING.value,
            ResourceStatus.DESTROYED.value,
            ResourceStatus.FAILED.value,
        }
    ),
    ResourceStatus.DESTROYING.value: frozenset(
        {
            ResourceStatus.DESTROYED.value,
            ResourceStatus.FAILED.value,
        }
    ),
    ResourceStatus.DESTROYED.value: frozenset(),
    ResourceStatus.FAILED.value: frozenset(),
}

_TERMINAL_STATUS_VALUES: frozenset[str] = frozenset(s.value for s in TERMINAL_STATUSES)


def _is_allowed_recovery(from_status: str, to_status: str) -> bool:
    """Return True if converging from → to is a legitimate lost-event recovery.

    Uses the explicit ``_RECOVERY_TRANSITIONS`` relation rather than a total
    order, so paused/resuming → ready (the resume recovery) is permitted while
    backward regressions and moves out of terminal states are not. Unknown
    ``from_status`` values map to the empty set (no recovery).
    """
    return to_status in _RECOVERY_TRANSITIONS.get(from_status, frozenset())


# ---------------------------------------------------------------------------
# Reconcile functions
# ---------------------------------------------------------------------------


def _apply_locked_range_instance(
    instance: RangeInstance,
    authoritative_status: str,
) -> str:
    """Acquire a row lock, re-check, and apply a status transition for one stale RangeInstance.

    Handles the inner savepoint, re-lock under ``skip_locked=False``, idempotency
    re-check after acquiring the lock, and the ``apply_range_status`` call.

    Returns:
        One of ``"reconciled"``, ``"converged"``, ``"skipped"``, or ``"failed"``.
    """
    try:
        with transaction.atomic():
            # Re-fetch under lock so concurrent workers don't double-apply.
            try:
                locked_instance = RangeInstance.all_objects.select_for_update(skip_locked=False).get(pk=instance.pk)
            except RangeInstance.DoesNotExist:
                return "skipped"

            # Re-check after acquiring the lock — another worker may have
            # already converged this row — then guard the recovery transition.
            if locked_instance.status == authoritative_status:
                outcome = "converged"
            elif not _is_allowed_recovery(locked_instance.status, authoritative_status):
                outcome = "skipped"
            else:
                applied = apply_range_status(
                    locked_instance,
                    authoritative_status,
                )
                outcome = "reconciled" if applied else "converged"
    except Exception:
        # apply_range_status raised (transient DB/broker failure).  The
        # savepoint is rolled back by the atomic() context manager before
        # re-raising.  Log and count the failure so the batch continues;
        # the next reconciler pass or the SQS retry will handle this row.
        logger.exception(
            "reconcile_range_instances: apply_range_status raised for "
            "RangeInstance pk=%s — row skipped, batch continues",
            safe_log_id(instance.pk),
        )
        return "failed"

    return outcome


def stale_range_instances_queryset(cutoff: datetime, batch_size: int) -> QuerySet[RangeInstance]:
    """Locked queryset of stale, non-terminal, live RangeInstance rows.

    ``of=("self",)`` scopes ``FOR UPDATE`` to the ``RangeInstance`` base table:
    ``select_related("request")`` LEFT-joins a nullable FK, and Postgres rejects
    ``FOR UPDATE`` on the nullable side of an outer join (#1395). SQLite drops
    row locking entirely, which is why this only surfaced against Postgres.
    """
    return (
        RangeInstance.all_objects.filter(
            deleted_at__isnull=True,
            status__in=[s.value for s in ResourceStatus if s.value not in _TERMINAL_STATUS_VALUES],
            updated_at__lt=cutoff,
        )
        .select_related("request")
        .select_for_update(skip_locked=True, of=("self",))[:batch_size]
    )


def reconcile_range_instances(
    stale_seconds: int,
    batch_size: int,
) -> dict[str, int]:
    """Reconcile stale RangeInstance rows against authoritative engine.Range status.

    Args:
        stale_seconds: Minimum age (in seconds) of ``updated_at`` before a row
            is considered stale.
        batch_size: Maximum number of rows to process in this run.

    Returns:
        Counts dict with keys ``reconciled``, ``converged``, ``skipped``,
        ``no_engine_range``.
    """
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    counts: dict[str, int] = {
        "reconciled": 0,
        "converged": 0,
        "skipped": 0,
        "no_engine_range": 0,
        "failed": 0,
    }

    with transaction.atomic():
        stale_instances = list(stale_range_instances_queryset(cutoff, batch_size))

    for instance in stale_instances:
        request_id = instance.request.request_id if instance.request else None
        authoritative_status = get_authoritative_range_status(
            request_id=request_id,
            range_id=instance.range_id,
        )

        if authoritative_status is None:
            logger.warning(
                "reconcile_range_instances: no engine.Range found for RangeInstance pk=%s (skipping)",
                safe_log_id(instance.pk),
            )
            counts["no_engine_range"] += 1
            continue

        if instance.status == authoritative_status:
            counts["converged"] += 1
            continue

        if not _is_allowed_recovery(instance.status, authoritative_status):
            logger.debug(
                "reconcile_range_instances: status %s->%s is not a forward move for RangeInstance pk=%s (skipping)",
                instance.status,
                authoritative_status,
                safe_log_id(instance.pk),
            )
            counts["skipped"] += 1
            continue

        logger.warning(
            "reconcile_range_instances: drift detected — RangeInstance pk=%s "
            "status=%s but engine.Range status=%s; re-driving projection",
            safe_log_id(instance.pk),
            instance.status,
            authoritative_status,
        )
        outcome = _apply_locked_range_instance(instance, authoritative_status)
        counts[outcome] += 1

    return counts


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    """Reconcile stale CMS projection rows against authoritative engine state.

    Scans for RangeInstance rows whose status has not advanced despite the
    corresponding engine.Range having moved forward, and re-drives the
    appropriate domain transition. Runs once by default (suitable for a
    CronJob); use --loop for persistent polling.
    """

    help = (
        "Reconcile stale CMS RangeInstance rows against authoritative "
        "engine.Range status. Runs once by default (suitable "
        "for a CronJob); use --loop for persistent polling."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--loop",
            action="store_true",
            default=False,
            help="Run in a continuous loop instead of exiting after one batch.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=60,
            help="Seconds between loop iterations (only used with --loop). Default: 60.",
        )
        parser.add_argument(
            "--stale-seconds",
            type=int,
            default=None,
            help=("Override RANGE_RECONCILE_STALE_SECONDS for this run. Defaults to the settings value."),
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help=("Override RANGE_RECONCILE_BATCH_SIZE for this run. Defaults to the settings value."),
        )

    def handle(self, *args, **options) -> None:
        stale_seconds: int = options["stale_seconds"] or getattr(settings, "RANGE_RECONCILE_STALE_SECONDS", 300)
        batch_size: int = options["batch_size"] or getattr(settings, "RANGE_RECONCILE_BATCH_SIZE", 100)
        loop: bool = options["loop"]
        interval: int = options["interval"]

        logger.info(
            "reconcile_range_events: starting (stale_seconds=%d batch_size=%d loop=%s)",
            stale_seconds,
            batch_size,
            loop,
        )

        while True:
            self._run_once(stale_seconds, batch_size)
            if not loop:
                break
            self._touch_heartbeat()
            time.sleep(interval)

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

    def _run_once(self, stale_seconds: int, batch_size: int) -> None:
        """Execute one reconciliation pass and log the summary."""
        ri_counts = reconcile_range_instances(stale_seconds, batch_size)

        total_reconciled = ri_counts["reconciled"]
        total_converged = ri_counts["converged"]
        total_skipped = ri_counts["skipped"]
        total_no_engine = ri_counts["no_engine_range"]

        log_fn = logger.warning if total_reconciled > 0 else logger.info
        log_fn(
            "reconcile_range_events: pass complete — "
            "reconciled=%d converged=%d skipped=%d no_engine_range=%d "
            "(range_instances: %r)",
            total_reconciled,
            total_converged,
            total_skipped,
            total_no_engine,
            ri_counts,
        )
