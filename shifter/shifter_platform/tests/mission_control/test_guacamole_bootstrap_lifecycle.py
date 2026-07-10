"""Behavior tests for the Guacamole bootstrap token lifecycle (issue #939).

Covers the three at-rest token controls: single-use consume-and-clear at the
delivery boundary, no-persist-after-expiry in the worker, and bounded scheduled
pruning of expired rows.
"""

from __future__ import annotations

from datetime import timedelta
from threading import BoundedSemaphore

import pytest
from django.utils import timezone

from mission_control.guacamole_bootstrap import (
    consume_ready_url,
    prune_expired_bootstrap_requests,
)
from mission_control.models import GuacamoleBootstrapRequest

pytestmark = pytest.mark.django_db


def _make(
    *,
    status=GuacamoleBootstrapRequest.Status.SUCCEEDED,
    user_id=1,
    result_url="",
    ttl_seconds=300,
    delivered_at=None,
):
    return GuacamoleBootstrapRequest.objects.create(
        user_id=user_id,
        protocol=GuacamoleBootstrapRequest.Protocol.RDP,
        target_id="vm-1",
        status=status,
        result_url=result_url,
        delivered_at=delivered_at,
        expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
    )


class TestConsumeReadyUrl:
    def test_delivers_once_and_clears(self):
        row = _make(result_url="https://guac/token")

        url = consume_ready_url(request_id=row.id, user_id=row.user_id)

        assert url == "https://guac/token"
        row.refresh_from_db()
        assert row.result_url == ""
        assert row.delivered_at is not None

    def test_second_consume_returns_none(self):
        row = _make(result_url="https://guac/token")

        assert consume_ready_url(request_id=row.id, user_id=row.user_id) == "https://guac/token"
        assert consume_ready_url(request_id=row.id, user_id=row.user_id) is None

    def test_wrong_user_is_not_delivered(self):
        row = _make(result_url="https://guac/token", user_id=1)

        assert consume_ready_url(request_id=row.id, user_id=2) is None
        row.refresh_from_db()
        assert row.result_url == "https://guac/token"

    def test_expired_returns_none_and_clears_parked_token(self):
        row = _make(result_url="https://guac/token", ttl_seconds=-1)

        assert consume_ready_url(request_id=row.id, user_id=row.user_id) is None
        row.refresh_from_db()
        assert row.result_url == ""

    def test_not_succeeded_is_not_delivered(self):
        row = _make(status=GuacamoleBootstrapRequest.Status.PENDING)

        assert consume_ready_url(request_id=row.id, user_id=row.user_id) is None


class TestPruneExpiredBootstrapRequests:
    def test_deletes_expired_only(self):
        expired = _make(ttl_seconds=-10)
        active = _make(ttl_seconds=300)

        deleted = prune_expired_bootstrap_requests()

        assert deleted == 1
        assert not GuacamoleBootstrapRequest.objects.filter(pk=expired.id).exists()
        assert GuacamoleBootstrapRequest.objects.filter(pk=active.id).exists()

    def test_does_not_delete_active_pending_or_running(self):
        _make(status=GuacamoleBootstrapRequest.Status.PENDING, ttl_seconds=300)
        _make(status=GuacamoleBootstrapRequest.Status.RUNNING, ttl_seconds=300)

        assert prune_expired_bootstrap_requests() == 0
        assert GuacamoleBootstrapRequest.objects.count() == 2

    def test_also_deletes_expired_pending_and_running(self):
        # Zombie rows: a worker crashed/timed out leaving PENDING/RUNNING rows
        # past their TTL. The prune deletes every expired row regardless of
        # status, not just SUCCEEDED, so these do not accumulate unbounded.
        expired_pending = _make(status=GuacamoleBootstrapRequest.Status.PENDING, ttl_seconds=-10)
        expired_running = _make(status=GuacamoleBootstrapRequest.Status.RUNNING, ttl_seconds=-10)
        active = _make(ttl_seconds=300)

        deleted = prune_expired_bootstrap_requests()

        assert deleted == 2
        assert not GuacamoleBootstrapRequest.objects.filter(pk=expired_pending.id).exists()
        assert not GuacamoleBootstrapRequest.objects.filter(pk=expired_running.id).exists()
        assert GuacamoleBootstrapRequest.objects.filter(pk=active.id).exists()

    def test_respects_batch_bound(self):
        for _ in range(3):
            _make(ttl_seconds=-10)

        deleted = prune_expired_bootstrap_requests(batch_size=2)

        assert deleted == 2
        assert GuacamoleBootstrapRequest.objects.count() == 1

    def test_no_expired_rows_returns_zero(self):
        _make(ttl_seconds=300)

        assert prune_expired_bootstrap_requests() == 0


class TestWorkerNoPersistAfterExpiry:
    def test_build_finishing_after_expiry_does_not_persist_url(self):
        from mission_control.guacamole_bootstrap import _run_bootstrap

        row = _make(status=GuacamoleBootstrapRequest.Status.RUNNING, ttl_seconds=-1)
        slots = BoundedSemaphore(1)
        slots.acquire()

        _run_bootstrap(row.id, lambda: "https://guac/late-token", slots)

        row.refresh_from_db()
        assert row.status == GuacamoleBootstrapRequest.Status.FAILED
        assert row.result_url == ""
        assert row.error_status_code == 410


class TestPruneCommand:
    def test_prune_cycle_deletes_expired(self):
        from mission_control.management.commands.run_guacamole_bootstrap_prune import Command

        _make(ttl_seconds=-10)
        _make(ttl_seconds=-10)
        active = _make(ttl_seconds=300)

        deleted = Command()._prune_cycle(batch_size=500)

        assert deleted == 2
        assert GuacamoleBootstrapRequest.objects.filter(pk=active.id).exists()

    def test_prune_cycle_drains_in_batches(self):
        from mission_control.management.commands.run_guacamole_bootstrap_prune import Command

        for _ in range(3):
            _make(ttl_seconds=-10)

        # batch_size below the backlog forces multiple batches within one cycle.
        deleted = Command()._prune_cycle(batch_size=2)

        assert deleted == 3
        assert GuacamoleBootstrapRequest.objects.count() == 0

    def test_signal_handler_sets_shutdown(self):
        import signal

        from mission_control.management.commands.run_guacamole_bootstrap_prune import Command

        cmd = Command()
        assert cmd.shutdown is False
        cmd._signal_handler(signal.SIGTERM, None)
        assert cmd.shutdown is True

    def test_add_arguments_exposes_settings_driven_defaults(self):
        from argparse import ArgumentParser

        from mission_control.management.commands.run_guacamole_bootstrap_prune import Command

        parser = ArgumentParser()
        Command().add_arguments(parser)
        namespace = parser.parse_args([])

        assert namespace.poll_interval >= 1
        assert namespace.batch_size >= 1

    def test_handle_runs_one_cycle_then_shuts_down(self, monkeypatch):
        from mission_control.management.commands import run_guacamole_bootstrap_prune as mod

        monkeypatch.setattr(mod.signal, "signal", lambda *args, **kwargs: None)
        _make(ttl_seconds=-10)
        cmd = mod.Command()
        results = []
        original_cycle = cmd._prune_cycle

        def one_then_stop(batch_size):
            deleted = original_cycle(batch_size)
            results.append(deleted)
            cmd.shutdown = True
            return deleted

        monkeypatch.setattr(cmd, "_prune_cycle", one_then_stop)
        cmd.handle(poll_interval=1, batch_size=10)

        assert results == [1]
        assert not mod.HEARTBEAT_FILE.exists()

    def test_handle_survives_a_cycle_error(self, monkeypatch):
        from mission_control.management.commands import run_guacamole_bootstrap_prune as mod

        monkeypatch.setattr(mod.signal, "signal", lambda *args, **kwargs: None)
        cmd = mod.Command()

        def boom(batch_size):
            cmd.shutdown = True
            raise RuntimeError("transient db blip")

        monkeypatch.setattr(cmd, "_prune_cycle", boom)
        # The loop must log and exit cleanly on shutdown, never propagate.
        cmd.handle(poll_interval=1, batch_size=10)

        assert not mod.HEARTBEAT_FILE.exists()
