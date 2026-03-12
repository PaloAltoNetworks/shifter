"""Tests for CTF Notification service."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from ctf.enums import NotificationStatus, NotificationType
from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFNotification
from ctf.services import notification
from ctf.services import participant as participant_service


@pytest.mark.django_db
class TestSendInvitations:
    """Tests for send_invitations."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent event."""
        with pytest.raises(CTFNotFoundError):
            notification.send_invitations(uuid4())

    def test_sends_to_uninvited(self, ctf_event, ctf_participant_invited):
        """Sends invitations and updates invited_at."""
        # Clear invited_at so this participant is eligible
        ctf_participant_invited.invited_at = None
        ctf_participant_invited.save(update_fields=["invited_at"])

        with patch.object(notification, "_send_email", return_value=True):
            result = notification.send_invitations(ctf_event.pk)

        assert result["sent"] == 1
        ctf_participant_invited.refresh_from_db()
        assert ctf_participant_invited.invited_at is not None

    def test_skips_already_invited(self, ctf_event, ctf_participant_invited):
        """Skips participants already invited."""
        # ctf_participant_invited already has invited_at set
        with patch.object(notification, "_send_email", return_value=True):
            result = notification.send_invitations(ctf_event.pk)

        assert result["sent"] == 0

    def test_tracks_failures(self, ctf_event, ctf_participant_invited):
        """Tracks failed sends."""
        ctf_participant_invited.invited_at = None
        ctf_participant_invited.save(update_fields=["invited_at"])

        with patch.object(notification, "_send_email", return_value=False):
            result = notification.send_invitations(ctf_event.pk)

        assert result["failed"] == 1
        assert result["sent"] == 0

    def test_creates_notification_record(self, ctf_event, ctf_participant_invited):
        """Creates CTFNotification record on success."""
        ctf_participant_invited.invited_at = None
        ctf_participant_invited.save(update_fields=["invited_at"])

        with patch.object(notification, "_send_email", return_value=True):
            notification.send_invitations(ctf_event.pk)

        notif = CTFNotification.objects.filter(
            event=ctf_event,
            notification_type=NotificationType.INVITE.value,
        ).first()
        assert notif is not None
        assert notif.status == NotificationStatus.SENT.value


@pytest.mark.django_db
class TestSendCredentials:
    """Tests for send_credentials."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent event."""
        with pytest.raises(CTFNotFoundError):
            notification.send_credentials(uuid4())

    def test_sends_to_ready_ranges(self, ctf_event, ctf_participant):
        """Sends credentials to participants with ready ranges."""
        ctf_participant.range_status = "ready"
        ctf_participant.save(update_fields=["range_status"])

        with (
            patch.object(notification, "_send_email", return_value=True),
            patch("ctf.services.range.get_range_access_url", return_value="https://example.com"),
        ):
            result = notification.send_credentials(ctf_event.pk)

        assert result["sent"] == 1

    def test_skips_non_ready(self, ctf_event, ctf_participant):
        """Skips participants without ready ranges."""
        result = notification.send_credentials(ctf_event.pk)
        assert result["total"] == 0


@pytest.mark.django_db
class TestSendReminder:
    """Tests for send_reminder."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent event."""
        with pytest.raises(CTFNotFoundError):
            notification.send_reminder(uuid4())

    def test_sends_to_registered(self, ctf_event, ctf_participant):
        """Sends reminders to registered participants."""
        with patch.object(notification, "_send_email", return_value=True):
            result = notification.send_reminder(ctf_event.pk)

        assert result["sent"] == 1


@pytest.mark.django_db
class TestSendAnnouncement:
    """Tests for send_announcement."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent event."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User(pk=1)

        with pytest.raises(CTFNotFoundError):
            notification.send_announcement(uuid4(), "Test", "Body", user)

    def test_creates_and_sends(self, ctf_event, organizer_user, ctf_participant):
        """Creates notification record and sends to participants."""
        with patch.object(notification, "_send_email", return_value=True):
            result = notification.send_announcement(ctf_event.pk, "Announcement", "Hello everyone", organizer_user)

        assert isinstance(result, CTFNotification)
        assert result.status == NotificationStatus.SENT.value
        assert result.sent_count == 1
        assert result.sent_at is not None


@pytest.mark.django_db
class TestScheduleNotification:
    """Tests for schedule_notification."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent notification."""
        with pytest.raises(CTFNotFoundError):
            from django.utils import timezone

            notification.schedule_notification(uuid4(), timezone.now())

    def test_schedules_notification(self, ctf_event, organizer_user):
        """Sets SCHEDULED status and creates scheduled task."""
        from django.utils import timezone

        from ctf.models import CTFScheduledTask

        notif = CTFNotification.objects.create(
            event=ctf_event,
            notification_type=NotificationType.ANNOUNCEMENT.value,
            subject="Test",
            body="Body",
            status=NotificationStatus.DRAFT.value,
            recipient_filter="participants",
            created_by=organizer_user,
        )

        scheduled_time = timezone.now() + __import__("datetime").timedelta(hours=2)
        result = notification.schedule_notification(notif.pk, scheduled_time)

        assert result.status == NotificationStatus.SCHEDULED.value
        assert result.scheduled_at == scheduled_time

        task = CTFScheduledTask.objects.filter(event=ctf_event).first()
        assert task is not None
        assert task.scheduled_for == scheduled_time


@pytest.mark.django_db
class TestRenderEmail:
    """Tests for _render_email helper."""

    def test_renders_templates(self, ctf_event, ctf_participant):
        """Renders both HTML and text templates."""
        html, text = notification._render_email(
            "invitation",
            {
                "event": ctf_event,
                "participant": ctf_participant,
                "invite_token": "test-token",
            },
        )

        assert ctf_event.name in html
        assert ctf_event.name in text
        assert "test-token" in html
        assert "test-token" in text


@pytest.mark.django_db
class TestInvitedAtNotSetAtCreation:
    """Verify invite_participant and bulk_import don't set invited_at."""

    def test_invite_participant_does_not_set_invited_at(self, ctf_event):
        """invite_participant() should not set invited_at (send_invitations does)."""
        p = participant_service.invite_participant(
            event_id=ctf_event.pk,
            email="newinvite@test.com",
            name="New Invite",
        )
        assert p.invited_at is None

    def test_bulk_import_does_not_set_invited_at(self, ctf_event):
        """bulk_import_participants() should not set invited_at."""
        csv_content = "Alice,alice@test.com\nBob,bob@test.com"
        created = participant_service.bulk_import_participants(ctf_event.pk, csv_content)
        assert len(created) == 2
        for p in created:
            assert p.invited_at is None
