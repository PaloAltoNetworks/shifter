"""Retired notification writes and retained email-template rendering."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ctf.exceptions import CTFCommunicationError
from ctf.services import notification


@pytest.mark.parametrize(
    "name,args",
    [
        ("send_login_info", (uuid4(),)),
        ("send_credentials", (uuid4(),)),
        ("send_announcement", (uuid4(), "Subject", "Body", None)),
        ("schedule_notification", (uuid4(), None)),
        ("cancel_scheduled_notification", (uuid4(),)),
        ("deliver_scheduled_notification", (uuid4(),)),
        ("_deliver_announcement", (None,)),
    ],
)
def test_legacy_export_cannot_send(name, args):
    with pytest.raises(CTFCommunicationError) as exc:
        getattr(notification, name)(*args)
    assert exc.value.code == "CTF_COMMUNICATION_RETIRED"


@pytest.mark.parametrize(
    "name",
    [
        "notify_organizer_event_start",
        "notify_organizer_event_end",
        "notify_organizer_provision_failure",
        "notify_organizer_capacity_outcome",
    ],
)
def test_organizer_alert_never_broadcasts_to_participants(name):
    assert getattr(notification, name)(uuid4(), {}) == {"outcome": "channel_unavailable"}


@pytest.mark.django_db
def test_reminder_retry_uses_same_staged_campaign(ctf_event):
    from ctf.models import CommunicationCampaign, CommunicationIntent, CTFNotification

    first = notification.send_reminder(ctf_event.pk, hours_before=1)
    assert notification.send_reminder(ctf_event.pk, hours_before=1) == first
    assert first["outcome"] == "channel_unavailable"
    assert CommunicationCampaign.objects.count() == 1
    assert not CommunicationIntent.objects.exists()
    assert not CTFNotification.objects.exists()


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
