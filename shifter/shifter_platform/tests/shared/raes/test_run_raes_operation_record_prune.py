"""Tests for the RAES operation-record pruning service command (#1277)."""

from __future__ import annotations

import logging
import signal
from argparse import ArgumentParser
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.test import override_settings
from django.utils import timezone

from shared.management.commands.run_raes_operation_record_prune import HEARTBEAT_FILE, Command
from shared.models import RaesOperationRecord
from shared.raes.operations import RaesOperationRecordWrite, persist_raes_operation_record
from shared.schemas.raes_operation import canonical_raes_payload_digest

SOURCE_TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)


def _seed(retention_expires_at: datetime) -> RaesOperationRecord:
    payload = {"operation_id": "op-secretless", "accepted": True}
    return persist_raes_operation_record(
        RaesOperationRecordWrite(
            request_id=uuid4(),
            operation_id="op-secretless",
            idempotency_key=f"k-{uuid4()}",
            record_kind=RaesOperationRecord.RecordKind.OPERATION_RECEIPT,
            contract_version="operation-receipt-v1",
            source_timestamp=SOURCE_TS,
            payload=payload,
            payload_digest=canonical_raes_payload_digest(payload),
            retention_expires_at=retention_expires_at,
        )
    )


@pytest.mark.django_db
def test_prune_cycle_deletes_expired_and_retains_unexpired():
    now = timezone.now()
    expired = _seed(now - timedelta(days=1))
    unexpired = _seed(now + timedelta(days=1))

    deleted = Command()._prune_cycle(batch_size=100)

    assert deleted == 1
    assert not RaesOperationRecord.objects.filter(pk=expired.pk).exists()
    assert RaesOperationRecord.objects.filter(pk=unexpired.pk).exists()


@pytest.mark.django_db
def test_prune_cycle_drains_backlog_in_bounded_batches():
    now = timezone.now()
    for _ in range(5):
        _seed(now - timedelta(days=1))

    deleted = Command()._prune_cycle(batch_size=2)

    assert deleted == 5
    assert RaesOperationRecord.objects.count() == 0


@pytest.mark.django_db
def test_prune_cycle_is_bounded_per_cycle(monkeypatch):
    # A single cycle must not drain an unbounded backlog: it deletes at most
    # _MAX_BATCHES_PER_CYCLE * batch_size rows, leaving the rest for later cycles.
    monkeypatch.setattr("shared.management.commands.run_raes_operation_record_prune._MAX_BATCHES_PER_CYCLE", 2)
    now = timezone.now()
    for _ in range(5):
        _seed(now - timedelta(days=1))

    cmd = Command()
    first = cmd._prune_cycle(batch_size=1)
    assert first == 2
    assert RaesOperationRecord.objects.count() == 3

    second = cmd._prune_cycle(batch_size=1)
    assert second == 2
    assert RaesOperationRecord.objects.count() == 1


@pytest.mark.django_db
def test_prune_cycle_refreshes_heartbeat_between_batches(monkeypatch):
    # The liveness heartbeat is refreshed during a multi-batch drain, not only
    # after it finishes, so the liveness probe cannot kill the worker mid-drain.
    monkeypatch.setattr("shared.management.commands.run_raes_operation_record_prune._MAX_BATCHES_PER_CYCLE", 10)
    now = timezone.now()
    for _ in range(3):
        _seed(now - timedelta(days=1))

    cmd = Command()
    touches: list[int] = []
    monkeypatch.setattr(cmd, "_touch_heartbeat", lambda: touches.append(1))

    cmd._prune_cycle(batch_size=1)

    assert len(touches) >= 3


@override_settings(
    RAES_OPERATION_RECORD_PRUNE_INTERVAL_SECONDS=1234,
    RAES_OPERATION_RECORD_PRUNE_BATCH_SIZE=77,
)
def test_add_arguments_defaults_come_from_settings():
    parser = ArgumentParser()
    Command().add_arguments(parser)

    ns = parser.parse_args([])
    assert ns.poll_interval == 1234
    assert ns.batch_size == 77


def test_signal_handler_sets_shutdown():
    cmd = Command()
    assert cmd.shutdown is False

    cmd._signal_handler(signal.SIGTERM, None)

    assert cmd.shutdown is True


def test_prune_cycle_stops_immediately_on_shutdown():
    cmd = Command()
    cmd.shutdown = True

    # A shutdown requested before the cycle starts deletes nothing and returns.
    assert cmd._prune_cycle(batch_size=10) == 0


# transaction=True: the daemon's cycle calls close_old_connections(), which
# corrupts pytest-django's rolled-back wrapping transaction on PostgreSQL. SQLite
# tolerated it; a real backend does not (#1524).
@pytest.mark.django_db(transaction=True)
def test_handle_runs_one_cycle_then_shuts_down(monkeypatch):
    now = timezone.now()
    expired = _seed(now - timedelta(days=1))

    cmd = Command()
    # Register no real OS signal handlers in the test process.
    monkeypatch.setattr(
        "shared.management.commands.run_raes_operation_record_prune.signal.signal",
        lambda *args, **kwargs: None,
    )
    # One cycle, then request shutdown so the outer loop exits.
    real_cycle = cmd._prune_cycle

    def _one_shot(batch_size: int) -> int:
        deleted = real_cycle(batch_size)
        cmd.shutdown = True
        return deleted

    monkeypatch.setattr(cmd, "_prune_cycle", _one_shot)

    cmd.handle(poll_interval=1, batch_size=5)

    assert not RaesOperationRecord.objects.filter(pk=expired.pk).exists()
    # The heartbeat file is cleaned up on graceful shutdown.
    assert not HEARTBEAT_FILE.exists()


@pytest.mark.django_db
def test_prune_cycle_logs_counts_only_never_payloads(caplog):
    now = timezone.now()
    _seed(now - timedelta(days=1))

    with caplog.at_level(logging.INFO):
        Command()._prune_cycle(batch_size=100)

    log_text = " ".join(record.getMessage() for record in caplog.records)
    assert "1" in log_text
    assert "op-secretless" not in log_text
    assert "accepted" not in log_text
