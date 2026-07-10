"""DB-backed render behaviour for custom CTF email templates (issue #1095).

These integration-style tests exercise ``notification._render_email`` against
real ``CTFEmailTemplate`` rows (mock-based variants live in
``test_notification.py``). They verify the safe placeholder renderer and the
fail-closed fallback that prevents server-side template injection (CWE-1336).
"""

from __future__ import annotations

from ctf.models import CTFEmailTemplate
from ctf.services import notification

_INVITE_CONTEXT_URL = "https://example.test/register"


def _render_invitation(event, participant):
    return notification._render_email(
        "invitation",
        {"event": event, "participant": participant, "registration_url": _INVITE_CONTEXT_URL},
        event=event,
    )


class TestRenderCustomEmailTemplate:
    def test_substitutes_allowlisted_placeholders(self, ctf_event, ctf_participant):
        """A valid stored body is substituted from a real DB row."""
        CTFEmailTemplate.objects.create(
            event=ctf_event,
            notification_type="invite",
            subject="Custom Subject",
            html_body="<p>Hi {{ participant_name }} for {{ event_name }}</p>",
            text_body="Hi {{ participant_name }} for {{ event_name }}",
        )

        html, text, custom_subject = _render_invitation(ctf_event, ctf_participant)

        assert ctf_event.name in html
        assert ctf_participant.name in text
        assert custom_subject == "Custom Subject"

    def test_attribute_traversal_fails_closed(self, ctf_event, ctf_participant):
        """Dotted attribute access is never engine-rendered; falls back to default."""
        # bulk_create bypasses model validation, simulating a legacy row that
        # predates the validator. SENTINEL only appears if the body were used.
        CTFEmailTemplate.objects.bulk_create(
            [
                CTFEmailTemplate(
                    event=ctf_event,
                    notification_type="invite",
                    subject="Custom Subject",
                    html_body="<x>SENTINEL {{ event.created_by.password }}</x>",
                    text_body="SENTINEL {{ event.created_by.password }}",
                )
            ]
        )

        html, text, custom_subject = _render_invitation(ctf_event, ctf_participant)

        assert "SENTINEL" not in html
        assert "SENTINEL" not in text
        assert custom_subject == ""

    def test_template_tags_fail_closed(self, ctf_event, ctf_participant):
        """A stored body containing {% %} tags is not rendered; default is used."""
        CTFEmailTemplate.objects.bulk_create(
            [
                CTFEmailTemplate(
                    event=ctf_event,
                    notification_type="invite",
                    subject="Custom Subject",
                    html_body="{% load i18n %}<x>SENTINEL {{ event_name }}</x>",
                    text_body="SENTINEL {{ event_name }}",
                )
            ]
        )

        html, text, custom_subject = _render_invitation(ctf_event, ctf_participant)

        assert "SENTINEL" not in html
        assert "SENTINEL" not in text
        assert custom_subject == ""

    def test_html_values_are_escaped(self, ctf_event, ctf_participant):
        """Substituted values are HTML-escaped in the HTML body (XSS-safe)."""
        ctf_participant.name = "<script>alert(1)</script>"
        ctf_participant.save(update_fields=["name", "updated_at"])
        CTFEmailTemplate.objects.create(
            event=ctf_event,
            notification_type="invite",
            subject="",
            html_body="<p>{{ participant_name }}</p>",
            text_body="{{ participant_name }}",
        )

        html, text, _subject = _render_invitation(ctf_event, ctf_participant)

        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        # Plain-text body is not HTML-escaped.
        assert "<script>alert(1)</script>" in text
