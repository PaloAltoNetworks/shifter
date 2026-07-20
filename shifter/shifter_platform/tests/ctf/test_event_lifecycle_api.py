"""Event lifecycle, scheduler-control, and cleanup API flows (CTF-007, #526, CTF-1003)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ctf.enums import ScheduledTaskStatus, ScheduledTaskType
from ctf.models import CTFParticipant, CTFScheduledTask
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db


def _lifecycle(client, event, action):
    return call_json(client, "post", "api_event_lifecycle", kwargs={"event_id": event.id}, body={"action": action})


class TestLifecycleActions:
    def test_full_transition_chain(self, ctf_event_draft, authenticated_organizer_client):
        ctf_event = ctf_event_draft
        assert _lifecycle(authenticated_organizer_client, ctf_event, "open_registration").json()["status"] == (
            "registration"
        )
        assert _lifecycle(authenticated_organizer_client, ctf_event, "activate").json()["status"] == "active"
        assert _lifecycle(authenticated_organizer_client, ctf_event, "pause").json()["status"] == "paused"
        assert _lifecycle(authenticated_organizer_client, ctf_event, "resume").json()["status"] == "active"
        assert _lifecycle(authenticated_organizer_client, ctf_event, "end").json()["status"] == "ended"

    def test_invalid_transition_conflicts(self, ctf_event_draft, authenticated_organizer_client):
        resp = _lifecycle(authenticated_organizer_client, ctf_event_draft, "activate")
        assert resp.status_code == 409

    def test_open_registration_schedules_automation(self, ctf_event_draft, authenticated_organizer_client):
        resp = _lifecycle(authenticated_organizer_client, ctf_event_draft, "open_registration")
        assert resp.status_code == 200
        types = set(CTFScheduledTask.objects.filter(event=ctf_event_draft).values_list("task_type", flat=True))
        assert ScheduledTaskType.EVENT_START.value in types
        assert ScheduledTaskType.EVENT_END.value in types
        assert ScheduledTaskType.CLEANUP_RANGES.value in types
        assert ScheduledTaskType.CLEANUP_WARNING.value in types

    def test_cancel_notifies_participants(self, ctf_event_active, authenticated_organizer_client, monkeypatch):
        sent = {}

        def fake_announce(event_id, subject, body, created_by):
            sent.update({"event_id": event_id, "subject": subject})

        monkeypatch.setattr("ctf.services.notification.send_announcement", fake_announce)
        CTFParticipant.objects.create(
            event=ctf_event_active,
            email="p@test.com",
            name="P",
            status="active",
            registered_at=timezone.now(),
        )
        resp = _lifecycle(authenticated_organizer_client, ctf_event_active, "cancel")
        assert resp.json()["status"] == "cancelled"
        assert sent["event_id"] == ctf_event_active.pk
        assert "cancelled" in sent["subject"]


class TestTaskControls:
    @pytest.fixture
    def scheduled(self, ctf_event_draft, authenticated_organizer_client):
        _lifecycle(authenticated_organizer_client, ctf_event_draft, "open_registration")
        return ctf_event_draft, authenticated_organizer_client

    def test_task_listing(self, scheduled):
        event, client = scheduled
        resp = call_json(client, "get", "api_event_tasks", kwargs={"event_id": event.id})
        assert resp.status_code == 200
        types = [t["task_type"] for t in resp.json()["tasks"]]
        assert ScheduledTaskType.EVENT_START.value in types

    def test_run_now_makes_task_due(self, scheduled):
        event, client = scheduled
        task = CTFScheduledTask.objects.filter(event=event, task_type=ScheduledTaskType.EVENT_END.value).first()
        resp = call_json(client, "post", "api_event_task_run", kwargs={"event_id": event.id, "task_id": task.id})
        assert resp.status_code == 200
        task.refresh_from_db()
        assert task.scheduled_for <= timezone.now()
        assert task.is_due

    def test_run_now_rejects_completed_task(self, scheduled):
        event, client = scheduled
        task = CTFScheduledTask.objects.filter(event=event).first()
        task.mark_completed()
        resp = call_json(client, "post", "api_event_task_run", kwargs={"event_id": event.id, "task_id": task.id})
        assert resp.status_code == 409

    def test_defer_and_cancel_cleanup(self, scheduled):
        event, client = scheduled
        cleanup = CTFScheduledTask.objects.get(event=event, task_type=ScheduledTaskType.CLEANUP_RANGES.value)
        before = cleanup.scheduled_for

        resp = call_json(
            client, "post", "api_event_cleanup", kwargs={"event_id": event.id}, body={"action": "defer", "hours": 6}
        )
        assert resp.status_code == 200
        cleanup.refresh_from_db()
        assert cleanup.scheduled_for == before + timedelta(hours=6)

        resp = call_json(client, "post", "api_event_cleanup", kwargs={"event_id": event.id}, body={"action": "cancel"})
        assert resp.status_code == 200
        cleanup.refresh_from_db()
        assert cleanup.status == ScheduledTaskStatus.CANCELLED.value

        # Nothing pending anymore: further control attempts conflict.
        resp = call_json(client, "post", "api_event_cleanup", kwargs={"event_id": event.id}, body={"action": "cancel"})
        assert resp.status_code == 409


class TestSchedulerRetry:
    def test_retry_backs_off_then_fails(self, ctf_event):
        task = CTFScheduledTask.objects.create(
            event=ctf_event,
            task_type=ScheduledTaskType.SEND_REMINDER.value,
            scheduled_for=timezone.now(),
            max_retries=2,
        )
        assert task.retry_or_fail("boom-1") is True
        task.refresh_from_db()
        assert task.status == ScheduledTaskStatus.PENDING.value
        assert task.retry_count == 1
        assert task.scheduled_for > timezone.now()

        assert task.retry_or_fail("boom-2") is True
        task.refresh_from_db()
        assert task.retry_count == 2

        assert task.retry_or_fail("boom-3") is False
        task.refresh_from_db()
        assert task.status == ScheduledTaskStatus.FAILED.value
        assert task.error_message == "boom-3"


class TestEventEndCleanupWindow:
    def test_event_end_defers_to_pending_cleanup_task(self, ctf_event_active, monkeypatch):
        """The delayed-cleanup review window (CTF-703) is honored at event end."""
        from ctf.management.commands.run_ctf_scheduler import _handle_event_end

        ctf_event_active.event_end = timezone.now() - timedelta(minutes=1)
        ctf_event_active.save(update_fields=["event_end", "updated_at"])
        CTFScheduledTask.objects.create(
            event=ctf_event_active,
            task_type=ScheduledTaskType.CLEANUP_RANGES.value,
            scheduled_for=timezone.now() + timedelta(hours=2),
        )
        end_task = CTFScheduledTask.objects.create(
            event=ctf_event_active,
            task_type=ScheduledTaskType.EVENT_END.value,
            scheduled_for=timezone.now(),
        )
        called = []
        monkeypatch.setattr("ctf.services.range.cleanup_event_ranges", lambda event_id: called.append(event_id))

        _handle_event_end(end_task)

        ctf_event_active.refresh_from_db()
        assert ctf_event_active.status == "ended"
        assert called == []

    def test_event_end_cleans_up_without_pending_task(self, ctf_event_active, monkeypatch):
        from ctf.management.commands.run_ctf_scheduler import _handle_event_end

        ctf_event_active.event_end = timezone.now() - timedelta(minutes=1)
        ctf_event_active.save(update_fields=["event_end", "updated_at"])
        end_task = CTFScheduledTask.objects.create(
            event=ctf_event_active,
            task_type=ScheduledTaskType.EVENT_END.value,
            scheduled_for=timezone.now(),
        )
        called = []
        monkeypatch.setattr("ctf.services.range.cleanup_event_ranges", lambda event_id: called.append(event_id))

        _handle_event_end(end_task)

        assert called == [ctf_event_active.pk]


class TestCleanupWarning:
    def test_warning_email_counts(self, ctf_event_active, monkeypatch):
        from ctf.services.notification import send_cleanup_warning

        CTFParticipant.objects.create(
            event=ctf_event_active,
            email="warn@test.com",
            name="W",
            status="active",
            registered_at=timezone.now(),
        )
        sent = []
        monkeypatch.setattr(
            "ctf.services.notification._send_email",
            lambda **kwargs: sent.append(kwargs["recipient"]),
        )
        result = send_cleanup_warning(ctf_event_active.pk)
        assert result == {"sent": 1, "failed": 0}
        assert sent == ["warn@test.com"]
