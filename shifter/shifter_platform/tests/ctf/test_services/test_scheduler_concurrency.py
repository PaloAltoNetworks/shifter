"""Tests for CTF scheduler concurrency safety (#942).

Covers the multi-node portal failure modes from #911 review:
- CTF-3: long-running SPIN_UP_RANGES must heartbeat its task so the stale
  recovery sweep does not mark in-flight work FAILED.
- CTF-7: stale recovery must be settings-driven and cross-node safe.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ctf.enums import ParticipantStatus, ScheduledTaskStatus, ScheduledTaskType
from ctf.models import CTFParticipant, CTFScheduledTask


def _make_unregistered_participant(event, idx):
    """Create an unassigned, unregistered participant.

    With no linked user, provisioning fails fast ("must be registered") before
    any CMS/network call, so the throttled loop runs without external boundaries.
    """
    return CTFParticipant.objects.create(
        event=event,
        user=None,
        email=f"sched-hb-{idx}@test.com",
        name=f"Heartbeat Participant {idx}",
        status=ParticipantStatus.INVITED.value,
        invite_token=f"hb-{event.pk}-{idx}",
        invite_token_expires=timezone.now() + timedelta(days=7),
    )


def _make_task(event, status, *, updated_minutes_ago=0):
    """Create a RUNNING/PENDING scheduled task and backdate its updated_at."""
    task = CTFScheduledTask.objects.create(
        event=event,
        task_type=ScheduledTaskType.SPIN_UP_RANGES.value,
        scheduled_for=timezone.now(),
        status=status,
    )
    if updated_minutes_ago:
        CTFScheduledTask.objects.filter(pk=task.pk).update(
            updated_at=timezone.now() - timedelta(minutes=updated_minutes_ago)
        )
        task.refresh_from_db()
    return task


class TestRecoverStaleTasks:
    """_recover_stale_tasks must heartbeat-aware and settings-driven (CTF-3)."""

    @pytest.mark.django_db
    def test_old_running_task_marked_failed(self, ctf_event, settings):
        """A RUNNING task older than the stale window is marked FAILED."""
        settings.CTF_SCHEDULER_STALE_TASK_MINUTES = 30
        task = _make_task(event=ctf_event, status=ScheduledTaskStatus.RUNNING.value, updated_minutes_ago=31)

        from ctf.management.commands.run_ctf_scheduler import Command

        Command()._recover_stale_tasks()

        task.refresh_from_db()
        assert task.status == ScheduledTaskStatus.FAILED.value
        assert "Stale" in task.error_message

    @pytest.mark.django_db
    def test_heartbeated_task_not_marked_failed(self, ctf_event, settings):
        """A RUNNING task with a fresh updated_at survives the sweep."""
        settings.CTF_SCHEDULER_STALE_TASK_MINUTES = 30
        task = _make_task(event=ctf_event, status=ScheduledTaskStatus.RUNNING.value, updated_minutes_ago=5)

        from ctf.management.commands.run_ctf_scheduler import Command

        Command()._recover_stale_tasks()

        task.refresh_from_db()
        assert task.status == ScheduledTaskStatus.RUNNING.value

    @pytest.mark.django_db
    def test_stale_window_reads_settings(self, ctf_event, settings):
        """The window is settings-driven: a larger window spares a 31-min task."""
        settings.CTF_SCHEDULER_STALE_TASK_MINUTES = 120
        task = _make_task(event=ctf_event, status=ScheduledTaskStatus.RUNNING.value, updated_minutes_ago=31)

        from ctf.management.commands.run_ctf_scheduler import Command

        Command()._recover_stale_tasks()

        task.refresh_from_db()
        assert task.status == ScheduledTaskStatus.RUNNING.value


class TestSpinUpHandlerHeartbeat:
    """_handle_spin_up_ranges must supply a heartbeat that touches updated_at."""

    @pytest.mark.django_db
    def test_handler_heartbeat_advances_updated_at(self, ctf_event):
        """Running the handler bumps the claimed task's updated_at via its heartbeat.

        A single unregistered participant drives exactly one (fast-failing,
        boundary-free) loop iteration, so no time.sleep is incurred and the
        heartbeat fires once against the real task row (#942).
        """
        _make_unregistered_participant(ctf_event, 0)
        task = _make_task(
            event=ctf_event,
            status=ScheduledTaskStatus.RUNNING.value,
            updated_minutes_ago=10,
        )
        before = task.updated_at

        from ctf.management.commands.run_ctf_scheduler import _handle_spin_up_ranges

        _handle_spin_up_ranges(task)

        task.refresh_from_db()
        assert task.updated_at > before
