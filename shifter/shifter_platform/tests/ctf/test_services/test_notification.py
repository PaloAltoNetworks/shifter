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


@pytest.mark.django_db
class TestSendInvitationsAsyncDispatchEndToEnd:
    """Integration coverage for PLAT-103 clause 3 in the invitation send loop.

    Drives ``send_invitations`` against real DB objects and the real render
    pipeline (per ADR-019-R1: no additional first-party mocking; only the
    external SMTP boundary is patched), proving the whole production path
    dispatches asynchronously without waiting on delivery.
    """

    def test_not_found(self):
        uuid4_2 = uuid4()
        with pytest.raises(CTFNotFoundError):
            notification.send_invitations(uuid4_2)

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


@pytest.fixture
def db_event(django_user_model):
    """Real organizer + REGISTRATION event for behavioral notification tests."""
    from datetime import timedelta

    from django.utils import timezone

    from ctf.enums import EventStatus
    from ctf.models import CTFEvent

    organizer = django_user_model.objects.create_user(
        username="notification-organizer@test.com",
        email="notification-organizer@test.com",
    )
    return CTFEvent.objects.create(
        name="Notification Event",
        description="Event for behavioral notification tests",
        created_by=organizer,
        status=EventStatus.REGISTRATION.value,
        event_start=timezone.now() + timedelta(days=1),
        event_end=timezone.now() + timedelta(days=1, hours=8),
        scenario_id="basic",
    )


@pytest.fixture
def db_participant(db_event):
    """Real invited + registered participant for db_event."""
    from django.utils import timezone

    from ctf.services.participant import invite_participant

    participant = invite_participant(
        event_id=db_event.pk,
        email="notification-participant@test.com",
        name="Notification Participant",
    )
    participant.registered_at = timezone.now()
    participant.save(update_fields=["registered_at", "updated_at"])
    return participant


@pytest.fixture
def recorded_email():
    """Record messages at the external SMTP boundary (ADR-019-R1).

    Replaces ``EmailMultiAlternatives`` with a recording double whose
    ``send()`` signals ``delivered``, so tests can wait deterministically on
    the real ``shared.email.send_email_async`` background dispatch and then
    assert on what crossed the boundary.
    """
    delivered = threading.Event()
    messages = []

    class RecordingMessage:
        def __init__(self, subject=None, body=None, from_email=None, to=None, **kwargs):
            self.subject = subject
            self.body = body
            self.from_email = from_email
            self.to = to
            messages.append(self)

        def attach_alternative(self, *args, **kwargs):
            pass

        def send(self):
            delivered.set()

    return RecordingMessage, delivered, messages


@pytest.mark.django_db
class TestSendCredentials:
    """Behavioral tests for send_credentials (real ORM + SMTP boundary)."""

    def test_not_found(self):
        missing_id = uuid4()
        with pytest.raises(CTFNotFoundError):
            notification.send_credentials(missing_id)

    def test_sends_to_ready_ranges(self, db_event, db_participant, recorded_email):
        """Dispatches credentials to participants with ready ranges."""
        from django.test import override_settings

        from ctf.models import CTFNotification

        db_participant.range_status = "ready"
        db_participant.save(update_fields=["range_status", "updated_at"])
        message_cls, delivered, messages = recorded_email

        with (
            override_settings(CTF_FROM_EMAIL="ctf@test.com", SITE_URL="https://example.com"),
            patch("django.core.mail.EmailMultiAlternatives", message_cls),
        ):
            result = notification.send_credentials(db_event.pk)
            assert delivered.wait(timeout=2), "background send never ran"

        assert result["sent"] == 1
        assert result["failed"] == 0
        assert messages[0].to == [db_participant.email]
        record = CTFNotification.objects.get(event=db_event, notification_type=NotificationType.CREDENTIALS.value)
        assert record.sent_count == 1
        assert record.status == NotificationStatus.SENT.value

    def test_skips_non_ready(self, db_event, db_participant):
        """Skips participants without ready ranges."""
        result = notification.send_credentials(db_event.pk)
        assert result["total"] == 0

    def test_render_failure_counted_as_failed(self, db_event, db_participant):
        """A synchronous rendering failure is counted in ``failed``; no
        dispatch occurs. Uses real DB objects and the real render pipeline;
        only the external template-loader boundary is patched (ADR-019-R1
        - no additional first-party mocking)."""
        db_participant.range_status = "ready"
        db_participant.save(update_fields=["range_status", "updated_at"])

        with patch("django.template.loader.render_to_string", side_effect=Exception("template error")):
            result = notification.send_credentials(db_event.pk)

        assert result["failed"] == 1
        assert result["sent"] == 0


@pytest.mark.django_db
class TestSendReminder:
    """Behavioral tests for send_reminder (real ORM + SMTP boundary)."""

    def _send_with_captured_templates(self, db_event, hours_before=None):
        """Run send_reminder with the template loader captured; return (result, contexts)."""
        from django.test import override_settings

        contexts = []

        def capture(template_name, context=None, *args, **kwargs):
            contexts.append(context or {})
            return "rendered"

        kwargs = {} if hours_before is None else {"hours_before": hours_before}
        with (
            override_settings(CTF_FROM_EMAIL="ctf@test.com", SITE_URL="https://example.com"),
            patch("django.template.loader.render_to_string", side_effect=capture),
        ):
            result = notification.send_reminder(db_event.pk, **kwargs)
        return result, contexts

    def test_not_found(self):
        missing_id = uuid4()
        with pytest.raises(CTFNotFoundError):
            notification.send_reminder(missing_id)

    def test_sends_to_registered(self, db_event, db_participant, recorded_email):
        """Sends reminders to registered participants and records the batch."""
        from django.test import override_settings

        from ctf.models import CTFNotification

        message_cls, delivered, messages = recorded_email
        with (
            override_settings(CTF_FROM_EMAIL="ctf@test.com", SITE_URL="https://example.com"),
            patch("django.core.mail.EmailMultiAlternatives", message_cls),
        ):
            result = notification.send_reminder(db_event.pk)
            assert delivered.wait(timeout=2), "background send never ran"

        assert result["sent"] == 1
        assert messages[0].to == [db_participant.email]
        record = CTFNotification.objects.get(event=db_event, notification_type=NotificationType.REMINDER.value)
        assert record.sent_count == 1

    def test_passes_access_url_and_timezone_to_template(self, db_event, db_participant):
        """Template context includes access_url, event_start_local, and event_timezone."""
        from datetime import datetime

        db_event.event_start = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)
        db_event.event_timezone = "America/New_York"
        db_event.save(update_fields=["event_start", "event_timezone", "updated_at"])

        result, contexts = self._send_with_captured_templates(db_event)

        assert result["sent"] == 1
        ctx = contexts[0]
        assert "access_url" in ctx
        assert ctx["access_url"].startswith("https://example.com/")
        assert "event_start_local" in ctx
        assert ctx["event_timezone"] == "America/New_York"

    def test_custom_hours_before(self, db_event, db_participant):
        """Accepts custom hours_before parameter."""
        result, _contexts = self._send_with_captured_templates(db_event, hours_before=1)
        assert result["hours_before"] == 1
        assert result["sent"] == 1

    def test_fallback_timezone_on_invalid(self, db_event, db_participant):
        """Falls back to UTC on invalid event_timezone."""
        from datetime import datetime

        db_event.event_start = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)
        db_event.event_timezone = "Invalid/Timezone"
        db_event.save(update_fields=["event_start", "event_timezone", "updated_at"])

        result, contexts = self._send_with_captured_templates(db_event)

        assert result["sent"] == 1
        assert contexts[0]["event_timezone"] == "UTC"


@pytest.mark.django_db
class TestSendAnnouncement:
    """Behavioral tests for send_announcement (real ORM)."""

    def test_not_found(self, django_user_model):
        user = django_user_model.objects.create_user(
            username="announcement-nf@test.com", email="announcement-nf@test.com"
        )
        missing_id = uuid4()
        with pytest.raises(CTFNotFoundError):
            notification.send_announcement(missing_id, "Test", "Body", user)

    def test_creates_and_sends(self, db_event, db_participant, recorded_email):
        """Creates the notification record and sends to participants."""
        from django.test import override_settings

        message_cls, delivered, messages = recorded_email
        with (
            override_settings(CTF_FROM_EMAIL="ctf@test.com", SITE_URL="https://example.com"),
            patch("django.core.mail.EmailMultiAlternatives", message_cls),
        ):
            result = notification.send_announcement(
                db_event.pk,
                "Announcement",
                "Hello everyone",
                db_event.created_by,
            )
            assert delivered.wait(timeout=2), "background send never ran"

        result.refresh_from_db()
        assert result.sent_count == 1
        assert result.status == NotificationStatus.SENT.value
        assert result.sent_at is not None
        assert messages[0].to == [db_participant.email]


@pytest.mark.django_db
class TestScheduleNotification:
    """Behavioral tests for schedule_notification (real ORM)."""

    def test_not_found(self):
        from django.utils import timezone

        missing_id = uuid4()
        now = timezone.now()
        with pytest.raises(CTFNotFoundError):
            notification.schedule_notification(missing_id, now)

    def test_schedules_notification(self, db_event):
        """Sets SCHEDULED status and creates the scheduled task row."""
        import datetime

        from django.utils import timezone

        from ctf.models import CTFNotification, CTFScheduledTask

        record = CTFNotification.objects.create(
            event=db_event,
            notification_type=NotificationType.ANNOUNCEMENT.value,
            subject="Scheduled announcement",
            body="Later",
            status=NotificationStatus.DRAFT.value,
            recipient_filter="participants",
            created_by=db_event.created_by,
        )
        scheduled_time = timezone.now() + datetime.timedelta(hours=2)

        result = notification.schedule_notification(record.pk, scheduled_time)

        assert result.status == NotificationStatus.SCHEDULED.value
        assert result.scheduled_at == scheduled_time
        task = CTFScheduledTask.objects.get(event=db_event)
        assert task.scheduled_for == scheduled_time
        assert task.metadata == {"notification_id": str(record.pk)}


# ---------------------------------------------------------------------------
# Organizer event start/end notifications (CTF-1004)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestNotifyOrganizerEventStart:
    """Behavioral tests for notify_organizer_event_start (real ORM + SMTP boundary)."""

    def test_sends_email_and_records_notification(self, db_event, recorded_email):
        """Sends email to the organizer and creates the notification record."""
        from django.test import override_settings

        from ctf.models import CTFNotification

        message_cls, delivered, messages = recorded_email
        with (
            override_settings(CTF_FROM_EMAIL="ctf@test.com", SITE_URL="https://example.com"),
            patch("django.core.mail.EmailMultiAlternatives", message_cls),
        ):
            notification.notify_organizer_event_start(db_event.pk)
            assert delivered.wait(timeout=2), "background send never ran"

        assert messages[0].to == [db_event.created_by.email]
        assert messages[0].subject == f"Event started: {db_event.name}"
        record = CTFNotification.objects.get(event=db_event, notification_type=NotificationType.EVENT_START.value)
        assert record.recipient_filter == "organizers"

    def test_event_not_found(self):
        """Returns gracefully if event does not exist."""
        notification.notify_organizer_event_start(uuid4())

    def test_no_organizer_email(self, db_event):
        """Returns gracefully, sending nothing, if the organizer has no email."""
        from ctf.models import CTFNotification

        organizer = db_event.created_by
        organizer.email = ""
        organizer.save(update_fields=["email"])

        notification.notify_organizer_event_start(db_event.pk)

        assert not CTFNotification.objects.filter(
            event=db_event, notification_type=NotificationType.EVENT_START.value
        ).exists()


@pytest.mark.django_db
class TestNotifyOrganizerEventEnd:
    """Behavioral tests for notify_organizer_event_end (real ORM + SMTP boundary)."""

    def test_sends_email_and_records_notification(self, db_event, recorded_email):
        """Sends email to the organizer and creates the notification record."""
        from django.test import override_settings

        from ctf.models import CTFNotification

        message_cls, delivered, messages = recorded_email
        with (
            override_settings(CTF_FROM_EMAIL="ctf@test.com", SITE_URL="https://example.com"),
            patch("django.core.mail.EmailMultiAlternatives", message_cls),
        ):
            notification.notify_organizer_event_end(db_event.pk)
            assert delivered.wait(timeout=2), "background send never ran"

        assert messages[0].to == [db_event.created_by.email]
        assert messages[0].subject == f"Event ended: {db_event.name}"
        record = CTFNotification.objects.get(event=db_event, notification_type=NotificationType.EVENT_END.value)
        assert record.recipient_filter == "organizers"

    def test_event_not_found(self):
        """Returns gracefully if event does not exist."""
        notification.notify_organizer_event_end(uuid4())

    def test_no_organizer_email(self, db_event):
        """Returns gracefully, sending nothing, if the organizer has no email."""
        from ctf.models import CTFNotification

        organizer = db_event.created_by
        organizer.email = ""
        organizer.save(update_fields=["email"])

        notification.notify_organizer_event_end(db_event.pk)

        assert not CTFNotification.objects.filter(
            event=db_event, notification_type=NotificationType.EVENT_END.value
        ).exists()


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
