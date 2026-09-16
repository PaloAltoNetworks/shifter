"""Tests for the ``reconcile_warm_pool`` managed-worker command (#28).

Pins the worker conventions: a single pass by default (CronJob-friendly), a
bounded ``--loop`` that touches a liveness heartbeat each iteration, and a
best-effort heartbeat that never aborts the loop on an OS error.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db

_SUMMARY = {"buckets": 1, "provisioned": 0, "retired": 0, "finalized": 0}


class _StopLoop(Exception):
    """Sentinel raised from a patched sleep to break the otherwise-infinite loop."""


def test_single_pass_runs_once(monkeypatch):
    calls: list = []
    monkeypatch.setattr("cms.services.reconcile_warm_pool", lambda: calls.append(1) or _SUMMARY)
    call_command("reconcile_warm_pool")
    assert calls == [1]


def test_loop_touches_heartbeat_and_polls(monkeypatch):
    calls: list = []
    monkeypatch.setattr("cms.services.reconcile_warm_pool", lambda: calls.append(1) or _SUMMARY)
    touched: list = []
    monkeypatch.setattr(
        "cms.management.commands.reconcile_warm_pool.Command._touch_heartbeat",
        lambda self: touched.append(1),
    )

    def _sleep(_seconds):
        raise _StopLoop

    monkeypatch.setattr("cms.management.commands.reconcile_warm_pool.time.sleep", _sleep)
    with pytest.raises(_StopLoop):
        call_command("reconcile_warm_pool", "--loop", "--interval", "0")
    assert calls == [1]
    assert touched == [1]


def test_heartbeat_swallows_os_error(monkeypatch):
    from cms.management.commands.reconcile_warm_pool import Command

    def _boom():
        raise OSError("read-only fs")

    monkeypatch.setattr(
        "cms.management.commands.reconcile_warm_pool.HEARTBEAT_FILE",
        type("_P", (), {"touch": staticmethod(_boom)})(),
    )
    # A heartbeat failure is logged, never raised.
    Command()._touch_heartbeat()
