"""Tests for CTF notification helpers, rendering, and the invited_at invariant.

Split from ``test_notification.py`` to keep each test module within the
behavior-scoped size limit (``test_test_suite_structure``). Covers the async
send choke point, template rendering, registration-URL construction, and the
``invited_at``-at-creation invariant. These tests use only third-party
(``django``) boundary patches or the real ORM.

The mock fixtures below mirror the shadowing fixtures in
``test_notification.py``: the shared ``tests/ctf/conftest.py`` fixtures of the
same name are DB-backed, but these notification tests deliberately use no-DB
mocks, so each module defines its own.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

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
def blocking_smtp():
    """A blocking, eventually-raising stand-in for ``EmailMultiAlternatives``.

    Drives the real ``shared.email.send_email_async`` background-thread pipeline
    (ADR-019-R1: mock the external SMTP boundary, not internal seams).
    ``send()`` blocks on ``release`` then raises after signalling ``delivered``,
    so a test can assert the caller returned before ``release`` was set.
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


class TestSendEmailHelper:
    """Tests for the _send_email choke point (PLAT-103 clause 3: async dispatch).

    ``_send_email`` is the single CTF send choke-point. It must dispatch
    through the real ``shared.email.send_email_async`` pipeline (fire-and-
    forget) rather than blocking on synchronous delivery, and must return
    ``None`` immediately regardless of how the background delivery eventually
    resolves. Per ADR-019-R1, these drive the real ``shared.email`` module
    end-to-end and only mock the external SMTP boundary
    (``django.core.mail.EmailMultiAlternatives``), rather than patching the
    first-party ``shared.email`` seam.
    """

    def test_returns_immediately_without_waiting_for_delivery(self, blocking_smtp):
        """Proves fire-and-forget: _send_email returns before the background
        SMTP layer runs, and a raising SMTP layer never surfaces to the caller."""
        from django.test import override_settings

        message_cls, release, delivered = blocking_smtp

        with (
            override_settings(CTF_FROM_EMAIL="ctf@test.com"),
            patch("django.core.mail.EmailMultiAlternatives", message_cls),
        ):
            result = notification._send_email(
                recipient="participant@test.com",
                subject="Subject line",
                html_content="<html>body</html>",
                text_content="body",
            )

            assert result is None
            assert not delivered.is_set()
            release.set()
            assert delivered.wait(timeout=2), "background send never ran"


class TestRenderEmail:
    """Tests for _render_email helper."""

    @patch("django.template.loader.render_to_string")
    def test_renders_templates(self, mock_render, ctf_event, ctf_participant):
        """Renders both HTML and text templates."""
        registration_url = "https://example.com/ctf/register/#token=test-token"

        mock_render.side_effect = [
            f"<html>{ctf_event.name} {registration_url}</html>",
            f"{ctf_event.name} {registration_url}",
        ]

        html, text, custom_subject = notification._render_email(
            "invitation",
            {
                "event": ctf_event,
                "participant": ctf_participant,
                "registration_url": registration_url,
            },
        )

        assert ctf_event.name in html
        assert ctf_event.name in text
        assert registration_url in html
        assert registration_url in text
        assert custom_subject == ""
        assert mock_render.call_count == 2


class TestBuildRegistrationUrl:
    """The invite token must ride in the URL fragment, never the query string."""

    def test_token_in_fragment_not_query_string(self):
        """_build_registration_url emits #token=, never ?token= (SonarCloud S8435)."""
        from django.test import override_settings

        with override_settings(SITE_URL="https://example.com"):
            url = notification._build_registration_url("abc123")

        assert url == "https://example.com/ctf/register/#token=abc123"
        assert "?token=" not in url
        assert "#token=abc123" in url


@pytest.mark.django_db
class TestInvitedAtNotSetAtCreation:
    """The real invite/import paths must not stamp ``invited_at`` at creation.

    ``invited_at`` is owned by ``send_invitations`` (it marks when the magic-link
    email actually went out), so creation must leave it unset. These tests run the
    real service functions against the real ORM (per ADR-019: no first-party
    internal patching) and assert on the observable persisted state — if the real
    code started stamping ``invited_at`` on creation, the assertion fails.
    """

    @pytest.fixture
    def importable_event(self, db):
        """A real registration-open event with no deadline / cap.

        Creates its own organizer user rather than reusing a shared fixture,
        because this module shadows the ``organizer_user`` name with a Mock.
        """
        from datetime import timedelta

        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from ctf.enums import EventStatus
        from ctf.models import CTFEvent

        creator = get_user_model().objects.create_user(
            username="invite-token-organizer@test.com",
            email="invite-token-organizer@test.com",
        )
        return CTFEvent.objects.create(
            name="Invite Token Event",
            description="Event for invited_at-at-creation tests",
            created_by=creator,
            status=EventStatus.REGISTRATION.value,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
            scenario_id="basic",
        )

    def test_invite_participant_does_not_set_invited_at(self, importable_event):
        """invite_participant() leaves invited_at unset on the created participant."""
        from ctf.services import participant as participant_service

        participant = participant_service.invite_participant(
            event_id=importable_event.pk,
            email="newinvite@test.com",
            name="New Invite",
        )

        assert participant.invited_at is None

    def test_bulk_import_does_not_set_invited_at(self, importable_event):
        """bulk_import_participants() leaves invited_at unset on every created participant."""
        from ctf.services import participant as participant_service

        csv_content = "Alice,alice@test.com\nBob,bob@test.com"
        created = participant_service.bulk_import_participants(importable_event.pk, csv_content)

        assert len(created) == 2
        for participant in created:
            assert participant.invited_at is None
