"""Tests for CTF Notification service."""

from __future__ import annotations

import threading
from datetime import UTC
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


@pytest.fixture
def blocking_smtp():
    """A blocking, eventually-raising stand-in for ``EmailMultiAlternatives``.

    Lets tests prove async dispatch (PLAT-103 clause 3) is non-blocking and
    delivery-failure-safe (clause 4) by driving the *real*
    ``shared.email.send_email_async`` background-thread pipeline, rather than
    mocking the first-party ``shared.email`` module (ADR-019-R1: mock the
    external SMTP boundary, not internal seams). ``send()`` blocks on
    ``release`` and raises after signalling ``delivered``, so a test can
    assert the caller returned *before* ``release`` was set.

    Returns:
        Tuple of ``(message_cls, release_event, delivered_event)``.
    """
    release = threading.Event()
    delivered = threading.Event()

    class BlockingMessage:
        def __init__(self, *args, **kwargs):
            pass

        def attach_alternative(self, *args, **kwargs):
            pass

        def send(self):
            release.wait(timeout=2)
            delivered.set()
            raise RuntimeError("SMTP exploded")

    return BlockingMessage, release, delivered


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
        """Dispatches invitations (async, fire-and-forget) and updates invited_at."""
        ctf_participant_invited.invited_at = None
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant_invited]

        with (
            patch.object(notification, "_send_email", return_value=None) as mock_send,
            patch.object(notification, "_build_registration_url", return_value="https://example.com/register"),
            patch.object(notification, "_render_email", return_value=("<html>", "text", "")),
        ):
            result = notification.send_invitations(ctf_event.pk)

        assert result["sent"] == 1
        mock_send.assert_called_once()
        ctf_participant_invited.save.assert_called()

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_sends_to_already_invited(
        self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant_invited
    ):
        """Dispatches to all participants including already-invited ones."""
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant_invited]

        with (
            patch.object(notification, "_send_email", return_value=None),
            patch.object(notification, "_build_registration_url", return_value="https://example.com/register"),
            patch.object(notification, "_render_email", return_value=("<html>", "text", "")),
        ):
            result = notification.send_invitations(ctf_event.pk)

        assert result["sent"] == 1

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_tracks_failures(self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant_invited):
        """A synchronous rendering failure (the surviving failure path under async
        delivery) is counted in ``failed`` and does not dispatch a send."""
        ctf_participant_invited.invited_at = None
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant_invited]

        with (
            patch.object(notification, "_send_email", return_value=None) as mock_send,
            patch.object(notification, "_build_registration_url", return_value="https://example.com/register"),
            patch.object(notification, "_render_email", side_effect=Exception("template error")),
        ):
            result = notification.send_invitations(ctf_event.pk)

        assert result["failed"] == 1
        assert result["sent"] == 0
        mock_send.assert_not_called()

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_creates_notification_record(
        self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant_invited
    ):
        """Creates CTFNotification record after dispatch, with honest 'Queued' wording."""
        ctf_participant_invited.invited_at = None
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant_invited]

        with (
            patch.object(notification, "_send_email", return_value=None),
            patch.object(notification, "_build_registration_url", return_value="https://example.com/register"),
            patch.object(notification, "_render_email", return_value=("<html>", "text", "")),
        ):
            notification.send_invitations(ctf_event.pk)

        mock_notif_cls.objects.create.assert_called_once()
        call_kwargs = mock_notif_cls.objects.create.call_args.kwargs
        assert call_kwargs["event"] == ctf_event
        assert call_kwargs["notification_type"] == NotificationType.INVITE.value
        assert call_kwargs["status"] == NotificationStatus.SENT.value
        assert call_kwargs["sent_count"] == 1
        assert "Queued" in call_kwargs["body"]


@pytest.mark.django_db
class TestSendInvitationsAsyncDispatchEndToEnd:
    """Integration coverage for PLAT-103 clause 3 in the invitation send loop.

    Drives ``send_invitations`` against real DB objects and the real render
    pipeline (per ADR-019-R1: no additional first-party mocking; only the
    external SMTP boundary is patched), proving the whole production path
    dispatches asynchronously without waiting on delivery.
    """

    @pytest.fixture
    def invited_event_participant(self):
        from datetime import timedelta

        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from ctf.enums import EventStatus
        from ctf.models import CTFEvent
        from ctf.services.participant import invite_participant

        creator = get_user_model().objects.create_user(
            username="async-dispatch-organizer@test.com",
            email="async-dispatch-organizer@test.com",
        )
        event = CTFEvent.objects.create(
            name="Async Dispatch Event",
            description="Event for PLAT-103 clause 3 async dispatch coverage",
            created_by=creator,
            status=EventStatus.REGISTRATION.value,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
            scenario_id="basic",
        )
        participant = invite_participant(
            event_id=event.pk,
            email="async-dispatch-participant@test.com",
            name="Async Dispatch Participant",
        )
        return event, participant

    def test_dispatch_is_fire_and_forget(self, invited_event_participant, blocking_smtp):
        """The real send_invitations pipeline (real ORM, real templates)
        dispatches through the async choke point and returns without waiting
        for delivery — a raising SMTP layer inside the background thread does
        not block the loop or surface as a failure."""
        from django.test import override_settings

        event, participant = invited_event_participant
        message_cls, release, delivered = blocking_smtp

        with (
            override_settings(CTF_FROM_EMAIL="ctf@test.com", SITE_URL="https://example.com"),
            patch("django.core.mail.EmailMultiAlternatives", message_cls),
        ):
            result = notification.send_invitations(event.pk)
            # The loop already returned; the background send has not run yet.
            assert not delivered.is_set()
            release.set()
            assert delivered.wait(timeout=2), "background send never ran"

        assert result["sent"] == 1
        assert result["failed"] == 0
        participant.refresh_from_db()
        assert participant.invited_at is not None


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
        """Dispatches credentials to participants with ready ranges."""
        ctf_participant.range_status = "ready"
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant]

        with (
            patch.object(notification, "_send_email", return_value=None) as mock_send,
            patch.object(notification, "_render_email", return_value=("<html>", "text", "")),
            patch("django.urls.reverse", return_value="/ctf/range/"),
        ):
            result = notification.send_credentials(ctf_event.pk)

        assert result["sent"] == 1
        mock_send.assert_called_once()

    @pytest.mark.django_db
    def test_render_failure_counted_as_failed(self):
        """A synchronous rendering failure is counted in ``failed``; no
        dispatch occurs. Uses real DB objects and the real render pipeline;
        only the external template-loader boundary is patched (ADR-019-R1
        - no additional first-party mocking)."""
        from datetime import timedelta

        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from ctf.enums import EventStatus
        from ctf.models import CTFEvent
        from ctf.services.participant import invite_participant

        creator = get_user_model().objects.create_user(
            username="credentials-render-failure-organizer@test.com",
            email="credentials-render-failure-organizer@test.com",
        )
        event = CTFEvent.objects.create(
            name="Credentials Render Failure Event",
            description="Event for the credentials render-failure test",
            created_by=creator,
            status=EventStatus.REGISTRATION.value,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
            scenario_id="basic",
        )
        participant = invite_participant(
            event_id=event.pk,
            email="credentials-render-failure-participant@test.com",
            name="Credentials Render Failure Participant",
        )
        participant.range_status = "ready"
        participant.save(update_fields=["range_status", "updated_at"])

        with patch("django.template.loader.render_to_string", side_effect=Exception("template error")):
            result = notification.send_credentials(event.pk)

        assert result["failed"] == 1
        assert result["sent"] == 0

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
            patch.object(notification, "_send_email", return_value=None),
            patch.object(notification, "_render_email", return_value=("<html>", "text", "")),
        ):
            result = notification.send_reminder(ctf_event.pk)

        assert result["sent"] == 1

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_passes_access_url_and_timezone_to_template(
        self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant
    ):
        """Template context includes access_url, event_start_local, and event_timezone."""
        from datetime import datetime

        ctf_event.event_start = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)
        ctf_event.event_timezone = "America/New_York"
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant]

        render_calls = []

        def capture_render(template_name, context, event=None):
            render_calls.append(context)
            return "<html>", "text", ""

        with (
            patch.object(notification, "_send_email", return_value=None),
            patch.object(notification, "_render_email", side_effect=capture_render),
            patch("django.urls.reverse", return_value="/ctf/event/"),
        ):
            notification.send_reminder(ctf_event.pk)

        assert len(render_calls) == 1
        ctx = render_calls[0]
        assert "access_url" in ctx
        assert "/ctf/event/" in ctx["access_url"]
        assert "event_start_local" in ctx
        assert ctx["event_timezone"] == "America/New_York"

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_custom_hours_before(self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant):
        """Accepts custom hours_before parameter."""
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant]

        with (
            patch.object(notification, "_send_email", return_value=None),
            patch.object(notification, "_render_email", return_value=("<html>", "text", "")),
        ):
            result = notification.send_reminder(ctf_event.pk, hours_before=1)

        assert result["hours_before"] == 1
        assert result["sent"] == 1

    @patch("ctf.services.notification.CTFNotification")
    @patch("ctf.services.notification.CTFParticipant")
    @patch("ctf.services.notification.CTFEvent")
    def test_fallback_timezone_on_invalid(
        self, mock_event_cls, mock_part_cls, mock_notif_cls, ctf_event, ctf_participant
    ):
        """Falls back to UTC on invalid event_timezone."""
        from datetime import datetime

        ctf_event.event_start = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)
        ctf_event.event_timezone = "Invalid/Timezone"
        mock_event_cls.objects.get.return_value = ctf_event
        mock_event_cls.DoesNotExist = Exception
        mock_part_cls.objects.filter.return_value = [ctf_participant]

        render_calls = []

        def capture_render(template_name, context, event=None):
            render_calls.append(context)
            return "<html>", "text", ""

        with (
            patch.object(notification, "_send_email", return_value=None),
            patch.object(notification, "_render_email", side_effect=capture_render),
            patch("django.urls.reverse", return_value="/ctf/event/"),
        ):
            result = notification.send_reminder(ctf_event.pk)

        assert result["sent"] == 1
        assert render_calls[0]["event_timezone"] == "UTC"


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
            patch.object(notification, "_send_email", return_value=None),
            patch.object(notification, "_render_email", return_value=("<html>", "text", "")),
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
            patch.object(notification, "_send_email", return_value=None) as mock_send,
            patch.object(notification, "_render_email", return_value=("<html>", "text", "")) as mock_render,
        ):
            notification.notify_organizer_event_start(ctf_event.pk)

        mock_render.assert_called_once_with("event_start", {"event": ctf_event}, event=ctf_event)
        mock_send.assert_called_once_with(
            recipient=ctf_event.created_by.email,
            subject=f"Event started: {ctf_event.name}",
            html_content="<html>",
            text_content="text",
        )
        mock_notif_cls.objects.create.assert_called_once()
        call_kwargs = mock_notif_cls.objects.create.call_args.kwargs
        assert call_kwargs["notification_type"] == NotificationType.EVENT_START.value
        assert call_kwargs["recipient_filter"] == "organizers"

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
            patch.object(notification, "_send_email", return_value=None) as mock_send,
            patch.object(notification, "_render_email", return_value=("<html>", "text", "")) as mock_render,
        ):
            notification.notify_organizer_event_end(ctf_event.pk)

        mock_render.assert_called_once_with("event_end", {"event": ctf_event}, event=ctf_event)
        mock_send.assert_called_once_with(
            recipient=ctf_event.created_by.email,
            subject=f"Event ended: {ctf_event.name}",
            html_content="<html>",
            text_content="text",
        )
        mock_notif_cls.objects.create.assert_called_once()
        call_kwargs = mock_notif_cls.objects.create.call_args.kwargs
        assert call_kwargs["notification_type"] == NotificationType.EVENT_END.value
        assert call_kwargs["recipient_filter"] == "organizers"

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


# ---------------------------------------------------------------------------
# Custom Email Template Tests
# ---------------------------------------------------------------------------


class TestRenderEmailWithCustomTemplate:
    """Tests for _render_email with per-event custom template overrides."""

    @patch("django.template.loader.render_to_string")
    def test_falls_back_to_default_when_no_custom(self, mock_render, ctf_event):
        """Uses filesystem template when no custom template exists."""
        mock_render.side_effect = ["<html>default</html>", "default"]

        with patch("ctf.models.CTFEmailTemplate.objects") as mock_qs:
            mock_qs.filter.return_value.first.return_value = None

            html, text, custom_subject = notification._render_email(
                "invitation",
                {"event": ctf_event},
                event=ctf_event,
            )

        assert html == "<html>default</html>"
        assert text == "default"
        assert custom_subject == ""
        assert mock_render.call_count == 2

    def test_uses_custom_template_when_present(self):
        """Renders from DB template via safe placeholder substitution."""

        class _SimpleEvent:
            name = "My Custom Event"
            description = ""
            event_start = None
            event_end = None

        event = _SimpleEvent()

        mock_template = MagicMock()
        mock_template.html_body = "<html>Hello {{ event_name }}</html>"
        mock_template.text_body = "Hello {{ event_name }}"
        mock_template.subject = "Custom Subject"

        with patch("ctf.models.CTFEmailTemplate.objects") as mock_qs:
            mock_qs.filter.return_value.first.return_value = mock_template

            html, text, custom_subject = notification._render_email(
                "invitation",
                {"event": event},
                event=event,
            )

        assert "My Custom Event" in html
        assert "My Custom Event" in text
        assert "<html>" in html
        assert custom_subject == "Custom Subject"

    @patch("django.template.loader.render_to_string")
    def test_no_db_lookup_when_event_is_none(self, mock_render):
        """Skips DB lookup when event is not provided (backward compat)."""
        mock_render.side_effect = ["<html>ok</html>", "ok"]

        html, _text, custom_subject = notification._render_email(
            "invitation",
            {"key": "value"},
        )

        assert html == "<html>ok</html>"
        assert custom_subject == ""
        assert mock_render.call_count == 2
