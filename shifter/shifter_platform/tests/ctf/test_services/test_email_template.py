"""Tests for the CTF safe email-template placeholder policy.

These exercise ``ctf.services.email_template`` — the single CTF-owned policy
that validates and renders organizer-authored custom email bodies without the
Django template engine (issue #1095, CWE-1336).
"""

from __future__ import annotations

from types import SimpleNamespace

from ctf.enums import NotificationType
from ctf.services import email_template


class TestFindTemplateViolations:
    """Validation of the flat ``{{ name }}`` placeholder grammar."""

    def test_valid_body_has_no_violations(self):
        allowed = email_template.allowed_placeholders(NotificationType.INVITE.value)
        body = "Hi {{ participant_name }}, join {{ event_name }} at {{ registration_url }}."
        assert email_template.find_template_violations(body, allowed) == []

    def test_rejects_template_tags(self):
        allowed = email_template.allowed_placeholders(NotificationType.INVITE.value)
        body = "{% if participant_name %}Hi{% endif %}"
        assert email_template.find_template_violations(body, allowed)

    def test_rejects_template_comments(self):
        allowed = email_template.allowed_placeholders(NotificationType.INVITE.value)
        body = "Hello {# secret #} world"
        assert email_template.find_template_violations(body, allowed)

    def test_rejects_dotted_attribute_access(self):
        allowed = email_template.allowed_placeholders(NotificationType.INVITE.value)
        body = "Hi {{ participant.user.password }}"
        assert email_template.find_template_violations(body, allowed)

    def test_rejects_filters(self):
        allowed = email_template.allowed_placeholders(NotificationType.INVITE.value)
        body = "Hi {{ participant_name|upper }}"
        assert email_template.find_template_violations(body, allowed)

    def test_rejects_unknown_placeholder(self):
        allowed = email_template.allowed_placeholders(NotificationType.INVITE.value)
        body = "Total: {{ failure_count }}"  # not allowed for invitations
        assert email_template.find_template_violations(body, allowed)

    def test_rejects_unbalanced_delimiters(self):
        allowed = email_template.allowed_placeholders(NotificationType.INVITE.value)
        body = "Hi {{ participant_name }"
        assert email_template.find_template_violations(body, allowed)

    def test_allowlist_is_per_notification_type(self):
        announcement = email_template.allowed_placeholders(NotificationType.ANNOUNCEMENT.value)
        invite = email_template.allowed_placeholders(NotificationType.INVITE.value)
        assert "body" in announcement
        assert "body" not in invite
        assert "registration_url" in invite
        assert "registration_url" not in announcement

    def test_unknown_notification_type_fails_closed(self):
        # An unmapped type gets no placeholders, so any placeholder is rejected.
        allowed = email_template.allowed_placeholders("not_a_real_type")
        assert allowed == frozenset()
        assert email_template.find_template_violations("Hi {{ event_name }}", allowed)

    def test_adversarial_brace_input_is_linear(self):
        # Regression for py/polynomial-redos: a long run of braces must not hang
        # and must be flagged as invalid, not silently accepted.
        allowed = email_template.allowed_placeholders(NotificationType.INVITE.value)
        evil = "{{" * 20000 + "a"
        assert email_template.find_template_violations(evil, allowed)


class TestBuildSafeContext:
    """The rich render context is flattened to scalar strings only."""

    def test_extracts_scalar_strings_only(self):
        event = SimpleNamespace(name="My Event", description="Desc", event_start=None, event_end=None)
        participant = SimpleNamespace(name="Alice", email="alice@example.com")
        scalars = email_template.build_safe_context(
            {
                "event": event,
                "participant": participant,
                "registration_url": "https://example.test/r",
            }
        )
        assert scalars["event_name"] == "My Event"
        assert scalars["participant_name"] == "Alice"
        assert scalars["registration_url"] == "https://example.test/r"
        assert all(isinstance(v, str) for v in scalars.values())

    def test_does_not_expose_objects(self):
        event = SimpleNamespace(name="E", description="", event_start=None, event_end=None)
        scalars = email_template.build_safe_context({"event": event})
        assert "event" not in scalars
        assert all(isinstance(v, str) for v in scalars.values())

    def test_formats_dates(self):
        from django.utils import timezone

        start = timezone.now()
        event = SimpleNamespace(name="E", description="", event_start=start, event_end=None)
        scalars = email_template.build_safe_context({"event": event})
        assert "event_start" in scalars
        assert isinstance(scalars["event_start"], str)
        assert scalars["event_start"]  # non-empty formatted date


class TestRenderSafeBody:
    """Substitution only replaces allowlisted flat placeholders."""

    def test_substitutes_known_placeholders(self):
        out = email_template.render_safe_body(
            "Hi {{ participant_name }} for {{ event_name }}",
            {"participant_name": "Alice", "event_name": "CTF"},
            escape=False,
        )
        assert out == "Hi Alice for CTF"

    def test_unknown_placeholder_renders_empty(self):
        out = email_template.render_safe_body("X{{ nope }}Y", {}, escape=False)
        assert out == "XY"

    def test_html_escapes_values_when_escape_true(self):
        out = email_template.render_safe_body(
            "<p>{{ event_name }}</p>",
            {"event_name": "<script>alert(1)</script>"},
            escape=True,
        )
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_text_body_not_escaped(self):
        out = email_template.render_safe_body(
            "{{ event_name }}",
            {"event_name": "A & B"},
            escape=False,
        )
        assert out == "A & B"
