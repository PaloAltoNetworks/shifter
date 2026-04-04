"""Tests for CTF scheduler event start/end handlers (CTF-1004)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def scheduled_task():
    """Mock CTFScheduledTask for event start/end."""
    task = MagicMock()
    task.event_id = uuid4()
    task.event = MagicMock()
    task.event.auto_cleanup = False
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

    @patch("ctf.services.notification.notify_organizer_event_end")
    @patch("ctf.services.event.complete_event", return_value=True)
    def test_calls_complete_and_notify(self, mock_complete, mock_notify, scheduled_task):
        """Completes event and notifies organizer on success."""
        from ctf.management.commands.run_ctf_scheduler import _handle_event_end

        _handle_event_end(scheduled_task)

        mock_complete.assert_called_once_with(scheduled_task.event)
        mock_notify.assert_called_once_with(scheduled_task.event_id)

    @patch("ctf.services.notification.notify_organizer_event_end")
    @patch("ctf.services.event.complete_event", return_value=False)
    def test_no_notify_on_failure(self, mock_complete, mock_notify, scheduled_task):
        """Does not notify organizer if completion fails."""
        from ctf.management.commands.run_ctf_scheduler import _handle_event_end

        _handle_event_end(scheduled_task)

        mock_complete.assert_called_once_with(scheduled_task.event)
        mock_notify.assert_not_called()

    @patch("ctf.services.range.cleanup_event_ranges", return_value={"ok": True})
    @patch("ctf.services.notification.notify_organizer_event_end")
    @patch("ctf.services.event.complete_event", return_value=True)
    def test_triggers_cleanup_when_enabled(self, mock_complete, mock_notify, mock_cleanup, scheduled_task):
        """Triggers range cleanup when auto_cleanup is enabled."""
        scheduled_task.event.auto_cleanup = True

        from ctf.management.commands.run_ctf_scheduler import _handle_event_end

        _handle_event_end(scheduled_task)

        mock_complete.assert_called_once_with(scheduled_task.event)
        mock_notify.assert_called_once_with(scheduled_task.event_id)
        mock_cleanup.assert_called_once_with(scheduled_task.event_id)
