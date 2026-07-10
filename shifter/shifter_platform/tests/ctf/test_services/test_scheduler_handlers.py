"""Tests for CTF scheduler handlers (CTF-1004, CTF-1005)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def scheduled_task():
    """Mock CTFScheduledTask for event start/end."""
    task = MagicMock()
    task.event_id = uuid4()
    task.event = MagicMock()
    task.event.pk = task.event_id
    task.event.auto_cleanup = False
    task.metadata = {}
    return task


class TestHandleEventStart:
    """Tests for _handle_event_start scheduler handler."""

    @patch("ctf.services.notification.notify_organizer_event_start")
    @patch("ctf.services.event.activate_event", return_value=True)
    def test_calls_activate_and_notify(self, mock_activate, mock_notify, scheduled_task):
        """Activates event and notifies organizer on success."""
        from ctf.management.commands.run_ctf_scheduler import _handle_event_start

        _handle_event_start(scheduled_task)

        mock_activate.assert_called_once_with(scheduled_task.event)
        mock_notify.assert_called_once_with(scheduled_task.event_id)

    @patch("ctf.services.notification.notify_organizer_event_start")
    @patch("ctf.services.event.activate_event", return_value=False)
    def test_no_notify_on_failure(self, mock_activate, mock_notify, scheduled_task):
        """Does not notify organizer if activation fails."""
        from ctf.management.commands.run_ctf_scheduler import _handle_event_start

        _handle_event_start(scheduled_task)

        mock_activate.assert_called_once_with(scheduled_task.event)
        mock_notify.assert_not_called()


class TestHandleEventEnd:
    """Tests for _handle_event_end scheduler handler."""

    @pytest.mark.django_db
    @patch("ctf.services.notification.notify_organizer_event_end")
    @patch("ctf.services.event.complete_event", return_value=True)
    def test_calls_complete_and_notify(self, mock_complete, mock_notify, ctf_event_active):
        """Completes event and notifies organizer on success."""
        from django.utils import timezone

        from ctf.enums import ScheduledTaskStatus, ScheduledTaskType
        from ctf.management.commands.run_ctf_scheduler import _handle_event_end
        from ctf.models import CTFScheduledTask

        ctf_event_active.event_end = timezone.now() - timedelta(minutes=1)
        ctf_event_active.save(update_fields=["event_end", "updated_at"])
        task = CTFScheduledTask.objects.create(
            event=ctf_event_active,
            task_type=ScheduledTaskType.EVENT_END.value,
            scheduled_for=ctf_event_active.event_end,
            status=ScheduledTaskStatus.PENDING.value,
        )

        _handle_event_end(task)

        mock_complete.assert_called_once()
        assert mock_complete.call_args.args[0].pk == ctf_event_active.pk
        mock_notify.assert_called_once_with(ctf_event_active.pk)

    @pytest.mark.django_db
    @patch("ctf.services.notification.notify_organizer_event_end")
    @patch("ctf.services.event.complete_event", return_value=False)
    def test_no_notify_on_failure(self, mock_complete, mock_notify, ctf_event_active):
        """Does not notify organizer if completion fails."""
        from django.utils import timezone

        from ctf.enums import ScheduledTaskStatus, ScheduledTaskType
        from ctf.management.commands.run_ctf_scheduler import _handle_event_end
        from ctf.models import CTFScheduledTask

        ctf_event_active.event_end = timezone.now() - timedelta(minutes=1)
        ctf_event_active.save(update_fields=["event_end", "updated_at"])
        task = CTFScheduledTask.objects.create(
            event=ctf_event_active,
            task_type=ScheduledTaskType.EVENT_END.value,
            scheduled_for=ctf_event_active.event_end,
            status=ScheduledTaskStatus.PENDING.value,
        )

        _handle_event_end(task)

        mock_complete.assert_called_once()
        mock_notify.assert_not_called()

    @pytest.mark.django_db
    @patch("ctf.services.range.cleanup_event_ranges", return_value={"ok": True})
    @patch("ctf.services.notification.notify_organizer_event_end")
    @patch("ctf.services.event.complete_event", return_value=True)
    def test_triggers_cleanup_when_enabled(self, mock_complete, mock_notify, mock_cleanup, ctf_event_active):
        """Triggers range cleanup when auto_cleanup is enabled."""
        from django.utils import timezone

        from ctf.enums import ScheduledTaskStatus, ScheduledTaskType
        from ctf.management.commands.run_ctf_scheduler import _handle_event_end
        from ctf.models import CTFScheduledTask

        ctf_event_active.auto_cleanup = True
        ctf_event_active.event_end = timezone.now() - timedelta(minutes=1)
        ctf_event_active.save(update_fields=["auto_cleanup", "event_end", "updated_at"])
        task = CTFScheduledTask.objects.create(
            event=ctf_event_active,
            task_type=ScheduledTaskType.EVENT_END.value,
            scheduled_for=ctf_event_active.event_end,
            status=ScheduledTaskStatus.PENDING.value,
        )

        _handle_event_end(task)

        mock_complete.assert_called_once()
        mock_notify.assert_called_once_with(ctf_event_active.pk)
        mock_cleanup.assert_called_once_with(ctf_event_active.pk)


class TestHandleSendReminder:
    """Tests for _handle_send_reminder scheduler handler (CTF-1005)."""

    @patch("ctf.services.notification.send_reminder", return_value={"sent": 3, "failed": 0})
    def test_calls_send_reminder_with_metadata_hours(self, mock_send, scheduled_task):
        """Uses hours_before from task metadata."""
        scheduled_task.metadata = {"hours_before": 1}

        from ctf.management.commands.run_ctf_scheduler import _handle_send_reminder

        _handle_send_reminder(scheduled_task)

        mock_send.assert_called_once_with(scheduled_task.event_id, hours_before=1)

    @patch("ctf.services.notification.send_reminder", return_value={"sent": 5, "failed": 0})
    def test_defaults_to_24_when_no_metadata(self, mock_send, scheduled_task):
        """Defaults to 24 hours when metadata is empty."""
        scheduled_task.metadata = {}

        from ctf.management.commands.run_ctf_scheduler import _handle_send_reminder

        _handle_send_reminder(scheduled_task)

        mock_send.assert_called_once_with(scheduled_task.event_id, hours_before=24)

    @patch("ctf.services.notification.send_reminder", return_value={"sent": 5, "failed": 0})
    def test_defaults_to_24_when_metadata_is_none(self, mock_send, scheduled_task):
        """Defaults to 24 hours when metadata is None."""
        scheduled_task.metadata = None

        from ctf.management.commands.run_ctf_scheduler import _handle_send_reminder

        _handle_send_reminder(scheduled_task)

        mock_send.assert_called_once_with(scheduled_task.event_id, hours_before=24)


@pytest.mark.django_db
class TestHandleSpinUpRanges:
    """_handle_spin_up_ranges converts the spin-up window, forwards the
    heartbeat to the throttled service, and returns its result so the
    dispatcher can detect interruption. With no unassigned participants the
    throttled loop is a no-op, which keeps this test free of CMS-boundary
    mocking."""

    def test_returns_throttled_result(self, ctf_event):
        from django.utils import timezone

        from ctf.enums import ScheduledTaskType
        from ctf.management.commands.run_ctf_scheduler import _handle_spin_up_ranges
        from ctf.models import CTFScheduledTask

        task = CTFScheduledTask.objects.create(
            event=ctf_event,
            task_type=ScheduledTaskType.SPIN_UP_RANGES.value,
            scheduled_for=timezone.now(),
        )

        result = _handle_spin_up_ranges(task, shutdown_check=lambda: False, heartbeat=MagicMock())

        assert result["interrupted"] is False
        assert result["total"] == 0


class TestExecuteTaskInterruption:
    """_execute_task records interruption as recoverable, not completed."""

    def _make_task(self):
        task = MagicMock()
        task.task_type = "spin_up_ranges"
        return task

    def test_requeues_on_interrupted_result(self, monkeypatch):
        from ctf.management.commands import run_ctf_scheduler as cmd

        task = self._make_task()

        def handler(_task, shutdown_check=None, heartbeat=None):
            return {"interrupted": True}

        monkeypatch.setitem(cmd.TASK_HANDLERS, "spin_up_ranges", handler)
        cmd.Command()._execute_task(task)

        task.requeue_for_resume.assert_called_once()
        task.mark_completed.assert_not_called()

    def test_completes_on_normal_result(self, monkeypatch):
        from ctf.management.commands import run_ctf_scheduler as cmd

        task = self._make_task()

        def handler(_task, shutdown_check=None, heartbeat=None):
            return {"interrupted": False}

        monkeypatch.setitem(cmd.TASK_HANDLERS, "spin_up_ranges", handler)
        cmd.Command()._execute_task(task)

        task.mark_completed.assert_called_once()
        task.requeue_for_resume.assert_not_called()

    def test_completes_on_none_result(self, monkeypatch):
        from ctf.management.commands import run_ctf_scheduler as cmd

        task = self._make_task()
        task.task_type = "event_start"

        def handler(_task, shutdown_check=None, heartbeat=None):
            return None

        monkeypatch.setitem(cmd.TASK_HANDLERS, "event_start", handler)
        cmd.Command()._execute_task(task)

        task.mark_completed.assert_called_once()

    def test_marks_failed_on_exception(self, monkeypatch):
        from ctf.management.commands import run_ctf_scheduler as cmd

        task = self._make_task()

        def handler(_task, shutdown_check=None, heartbeat=None):
            raise RuntimeError("boom")

        monkeypatch.setitem(cmd.TASK_HANDLERS, "spin_up_ranges", handler)
        cmd.Command()._execute_task(task)

        task.mark_failed.assert_called_once()
        task.mark_completed.assert_not_called()
        task.requeue_for_resume.assert_not_called()
