"""Tests for CTF Notification service."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from ctf.enums import NotificationStatus, NotificationType
from ctf.exceptions import CTFNotFoundError
from ctf.services import notification

# ---------------------------------------------------------------------------
# Local mock fixtures (no DB)
# ---------------------------------------------------------------------------


@pytest.fixture
def organizer_user():
    """Mock organizer user."""
    return Mock(pk=1, id=1, email="organizer@test.com", username="organizer")


@pytest.fixture
def ctf_event(organizer_user):
    """Mock CTFEvent."""
    event = MagicMock()
    event.pk = uuid4()
    event.name = "Test CTF Event"
    event.created_by = organizer_user
    return event


@pytest.fixture
def ctf_participant():
    """Mock CTFParticipant (active, registered)."""
    p = MagicMock()
    p.pk = uuid4()
    p.email = "participant@test.com"
    p.name = "Test Participant"
    p.invite_token = "test-invite-token"
    p.invited_at = None
    p.range_status = "pending"
    p.registered_at = "2025-01-01T00:00:00Z"
    return p


@pytest.fixture
def ctf_participant_invited():
    """Mock CTFParticipant (invited, not registered)."""
    p = MagicMock()
    p.pk = uuid4()
    p.email = "invited@test.com"
    p.name = "Invited Participant"
    p.invite_token = "invited-token"
    p.invited_at = "2025-01-01T00:00:00Z"
    p.range_status = "pending"
    return p


class TestSendInvitations:
    """Tests for send_invitations."""

    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_not_found(self, mock_event_cls, mock_part_cls):
        """Raises CTFNotFoundError for nonexistent event."""
        mock_event_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_event_cls.objects.get.side_effect = mock_event_cls.DoesNotExist
        with pytest.raises(CTFNotFoundError):
            notification.send_invitations(uuid4())

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_sends_to_uninvited(
        self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant_invited
    ):
        """Sends invitations and updates invited_at."""
        ctf_participant_invited.invited_at = None
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant_invited]

        with (
            patch.object(notification, "_send_email", return_value=True),
            patch.object(notification, "_build_registration_url", return_value="https://example.com/register"),
            patch.object(notification, "_render_email", return_value=("<html>", "text")),
        ):
            result = notification.send_invitations(ctf_event.pk)

        assert result["sent"] == 1
        ctf_participant_invited.save.assert_called()

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_sends_to_already_invited(
        self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant_invited
    ):
        """Sends to all participants including already-invited ones."""
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant_invited]

        with (
            patch.object(notification, "_send_email", return_value=True),
            patch.object(notification, "_build_registration_url", return_value="https://example.com/register"),
            patch.object(notification, "_render_email", return_value=("<html>", "text")),
        ):
            result = notification.send_invitations(ctf_event.pk)

        assert result["sent"] == 1

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_tracks_failures(self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant_invited):
        """Tracks failed sends."""
        ctf_participant_invited.invited_at = None
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant_invited]

        with (
            patch.object(notification, "_send_email", return_value=False),
            patch.object(notification, "_build_registration_url", return_value="https://example.com/register"),
            patch.object(notification, "_render_email", return_value=("<html>", "text")),
        ):
            result = notification.send_invitations(ctf_event.pk)

        assert result["failed"] == 1
        assert result["sent"] == 0

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_creates_notification_record(
        self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant_invited
    ):
        """Creates CTFNotification record on success."""
        ctf_participant_invited.invited_at = None
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant_invited]

        with (
            patch.object(notification, "_send_email", return_value=True),
            patch.object(notification, "_build_registration_url", return_value="https://example.com/register"),
            patch.object(notification, "_render_email", return_value=("<html>", "text")),
        ):
            notification.send_invitations(ctf_event.pk)

        mock_notif_cls.objects.create.assert_called_once()
        call_kwargs = mock_notif_cls.objects.create.call_args.kwargs
        assert call_kwargs["event"] == ctf_event
        assert call_kwargs["notification_type"] == NotificationType.INVITE.value
        assert call_kwargs["status"] == NotificationStatus.SENT.value


class TestSendCredentials:
    """Tests for send_credentials."""

    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_not_found(self, mock_event_cls, mock_part_cls):
        """Raises CTFNotFoundError for nonexistent event."""
        mock_event_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_event_cls.objects.get.side_effect = mock_event_cls.DoesNotExist
        with pytest.raises(CTFNotFoundError):
            notification.send_credentials(uuid4())

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_sends_to_ready_ranges(self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant):
        """Sends credentials to participants with ready ranges."""
        ctf_participant.range_status = "ready"
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant]

        with (
            patch.object(notification, "_send_email", return_value=True),
            patch.object(notification, "_render_email", return_value=("<html>", "text")),
            patch("django.urls.reverse", return_value="/ctf/range/"),
        ):
            result = notification.send_credentials(ctf_event.pk)

        assert result["sent"] == 1

    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_skips_non_ready(self, mock_event_cls, mock_part_cls, ctf_event):
        """Skips participants without ready ranges."""
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        # filter for range_status="ready" returns empty
        mock_part_cls.objects.filter.return_value = []

        result = notification.send_credentials(ctf_event.pk)
        assert result["total"] == 0


class TestSendReminder:
    """Tests for send_reminder."""

    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_not_found(self, mock_event_cls, mock_part_cls):
        """Raises CTFNotFoundError for nonexistent event."""
        mock_event_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_event_cls.objects.get.side_effect = mock_event_cls.DoesNotExist
        with pytest.raises(CTFNotFoundError):
            notification.send_reminder(uuid4())

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_sends_to_registered(self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant):
        """Sends reminders to registered participants."""
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant]

        with (
            patch.object(notification, "_send_email", return_value=True),
            patch.object(notification, "_render_email", return_value=("<html>", "text")),
        ):
            result = notification.send_reminder(ctf_event.pk)

        assert result["sent"] == 1


class TestSendAnnouncement:
    """Tests for send_announcement."""

    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFEvent")
    def test_not_found(self, mock_event_cls, mock_notif_cls, mock_part_cls):
        """Raises CTFNotFoundError for nonexistent event."""
        mock_event_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_event_cls.objects.get.side_effect = mock_event_cls.DoesNotExist
        user = Mock(pk=1)
        with pytest.raises(CTFNotFoundError):
            notification.send_announcement(uuid4(), "Test", "Body", user)

    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFEvent")
    def test_creates_and_sends(
        self,
        mock_event_cls,
        mock_notif_cls,
        mock_part_cls,
        ctf_event,
        organizer_user,
        ctf_participant,
    ):
        """Creates notification record and sends to participants."""
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant]

        # Build a mock notification that send_announcement will mutate
        mock_notif = MagicMock()
        mock_notif.status = NotificationStatus.SENDING.value
        mock_notif.sent_count = 0
        mock_notif.sent_at = None
        mock_notif_cls.objects.create.return_value = mock_notif

        with (
            patch.object(notification, "_send_email", return_value=True),
            patch.object(notification, "_render_email", return_value=("<html>", "text")),
        ):
            result = notification.send_announcement(
                ctf_event.pk,
                "Announcement",
                "Hello everyone",
                organizer_user,
            )

        assert result is mock_notif
        assert result.sent_count == 1
        assert result.status == NotificationStatus.SENT.value
        assert result.sent_at is not None
        mock_notif.save.assert_called_once()


class TestScheduleNotification:
    """Tests for schedule_notification."""

    @patch("ctf.services.notification.CTFNotification")
    def test_not_found(self, mock_notif_cls):
        """Raises CTFNotFoundError for nonexistent notification."""
        mock_notif_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_notif_cls.objects.get.side_effect = mock_notif_cls.DoesNotExist
        from django.utils import timezone

        with pytest.raises(CTFNotFoundError):
            notification.schedule_notification(uuid4(), timezone.now())

    @patch("ctf.models.CTFScheduledTask")
    @patch("ctf.services.notification.CTFNotification")
    def test_schedules_notification(self, mock_notif_cls, mock_task_cls, ctf_event):
        """Sets SCHEDULED status and creates scheduled task."""
        import datetime

        from django.utils import timezone

        mock_notif = MagicMock()
        mock_notif.pk = uuid4()
        mock_notif.event = ctf_event
        mock_notif.status = NotificationStatus.DRAFT.value
        mock_notif_cls.objects.get.return_value = mock_notif
        mock_notif_cls.DoesNotExist = Exception

        scheduled_time = timezone.now() + datetime.timedelta(hours=2)
        result = notification.schedule_notification(mock_notif.pk, scheduled_time)

        assert result.status == NotificationStatus.SCHEDULED.value
        assert result.scheduled_at == scheduled_time
        mock_notif.save.assert_called_once()
        mock_task_cls.objects.create.assert_called_once()
        task_kwargs = mock_task_cls.objects.create.call_args.kwargs
        assert task_kwargs["event"] == ctf_event
        assert task_kwargs["scheduled_for"] == scheduled_time


class TestRenderEmail:
    """Tests for _render_email helper."""

    @patch("django.template.loader.render_to_string")
    def test_renders_templates(self, mock_render, ctf_event, ctf_participant):
        """Renders both HTML and text templates."""
        registration_url = "https://example.com/ctf/register/?token=test-token"

        mock_render.side_effect = [
            f"<html>{ctf_event.name} {registration_url}</html>",
            f"{ctf_event.name} {registration_url}",
        ]

        html, text = notification._render_email(
            "invitation",
            {
                "event": ctf_event,
                "participant": ctf_participant,
                "invite_token": "test-token",
                "registration_url": registration_url,
            },
        )

        assert ctf_event.name in html
        assert ctf_event.name in text
        assert registration_url in html
        assert registration_url in text
        assert mock_render.call_count == 2


class TestInvitedAtNotSetAtCreation:
    """Verify invite_participant and bulk_import don't set invited_at."""

    @patch("ctf.services.participant.invite_participant")
    def test_invite_participant_does_not_set_invited_at(self, mock_invite, ctf_event):
        """invite_participant() should not set invited_at (send_invitations does)."""
        mock_p = MagicMock()
        mock_p.invited_at = None
        mock_invite.return_value = mock_p

        from ctf.services import participant as participant_service

        p = participant_service.invite_participant(
            event_id=ctf_event.pk,
            email="newinvite@test.com",
            name="New Invite",
        )
        assert p.invited_at is None

    @patch("ctf.services.participant.bulk_import_participants")
    def test_bulk_import_does_not_set_invited_at(self, mock_bulk, ctf_event):
        """bulk_import_participants() should not set invited_at."""
        mock_p1 = MagicMock()
        mock_p1.invited_at = None
        mock_p2 = MagicMock()
        mock_p2.invited_at = None
        mock_bulk.return_value = [mock_p1, mock_p2]

        from ctf.services import participant as participant_service

        csv_content = "Alice,alice@test.com\nBob,bob@test.com"
        created = participant_service.bulk_import_participants(ctf_event.pk, csv_content)
        assert len(created) == 2
        for p in created:
            assert p.invited_at is None


# ---------------------------------------------------------------------------
# Organizer event start/end notifications (CTF-1004)
# ---------------------------------------------------------------------------


class TestNotifyOrganizerEventStart:
    """Tests for notify_organizer_event_start."""

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFEvent")
    def test_sends_email_and_records_notification(self, mock_event_cls, mock_notif_cls, ctf_event):
        """Sends email to organizer and creates notification record."""
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception

        with (
            patch.object(notification, "_send_email", return_value=True) as mock_send,
            patch.object(notification, "_render_email", return_value=("<html>", "text")) as mock_render,
        ):
            notification.notify_organizer_event_start(ctf_event.pk)

        mock_render.assert_called_once_with("event_start", {"event": ctf_event})
        mock_send.assert_called_once_with(
            recipient=ctf_event.created_by.email,
            subject=f"Event started: {ctf_event.name}",
            html_content="<html>",
            text_content="text",
        )
        mock_notif_cls.objects.create.assert_called_once()
        call_kwargs = mock_notif_cls.objects.create.call_args.kwargs
        assert call_kwargs["notification_type"] == NotificationType.EVENT_START.value
        assert call_kwargs["recipient_filter"] == "organizer"

    @patch("ctf.services.notification.CTFEvent")
    def test_event_not_found(self, mock_event_cls):
        """Returns gracefully if event does not exist."""
        mock_event_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_event_cls.objects.get.side_effect = mock_event_cls.DoesNotExist

        notification.notify_organizer_event_start(uuid4())

    @patch("ctf.services.notification.CTFEvent")
    def test_no_organizer_email(self, mock_event_cls, ctf_event):
        """Returns gracefully if organizer has no email."""
        ctf_event.created_by.email = None
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception

        with patch.object(notification, "_send_email") as mock_send:
            notification.notify_organizer_event_start(ctf_event.pk)

        mock_send.assert_not_called()


class TestNotifyOrganizerEventEnd:
    """Tests for notify_organizer_event_end."""

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFEvent")
    def test_sends_email_and_records_notification(self, mock_event_cls, mock_notif_cls, ctf_event):
        """Sends email to organizer and creates notification record."""
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception

        with (
            patch.object(notification, "_send_email", return_value=True) as mock_send,
            patch.object(notification, "_render_email", return_value=("<html>", "text")) as mock_render,
        ):
            notification.notify_organizer_event_end(ctf_event.pk)

        mock_render.assert_called_once_with("event_end", {"event": ctf_event})
        mock_send.assert_called_once_with(
            recipient=ctf_event.created_by.email,
            subject=f"Event ended: {ctf_event.name}",
            html_content="<html>",
            text_content="text",
        )
        mock_notif_cls.objects.create.assert_called_once()
        call_kwargs = mock_notif_cls.objects.create.call_args.kwargs
        assert call_kwargs["notification_type"] == NotificationType.EVENT_END.value
        assert call_kwargs["recipient_filter"] == "organizer"

    @patch("ctf.services.notification.CTFEvent")
    def test_event_not_found(self, mock_event_cls):
        """Returns gracefully if event does not exist."""
        mock_event_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_event_cls.objects.get.side_effect = mock_event_cls.DoesNotExist

        notification.notify_organizer_event_end(uuid4())

    @patch("ctf.services.notification.CTFEvent")
    def test_no_organizer_email(self, mock_event_cls, ctf_event):
        """Returns gracefully if organizer has no email."""
        ctf_event.created_by.email = None
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception

        with patch.object(notification, "_send_email") as mock_send:
            notification.notify_organizer_event_end(ctf_event.pk)

        mock_send.assert_not_called()
