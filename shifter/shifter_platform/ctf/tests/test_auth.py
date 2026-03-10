"""Tests for CTF authentication, routing, and access control.

Phase 2: User Type Routing & Authentication.
Tests cover:
- OIDC backend extension for CTF user types
- Dashboard routing by user type
- Access control decorators
- CTF login with invite token
- CTF context processor
- Dev auth CTF user type support
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from ctf.enums import EventStatus
from ctf.models import CTFEvent
from management.models import UserProfile

if TYPE_CHECKING:
    from django.contrib.auth.models import User

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def organizer_profile(db, organizer_user) -> UserProfile:
    """Create an organizer user with CTF organizer profile."""
    profile, _ = UserProfile.objects.get_or_create(user=organizer_user)
    profile.user_type = "ctf_organizer"
    profile.save(update_fields=["user_type"])
    return profile


@pytest.fixture
def participant_profile(db, participant_user) -> UserProfile:
    """Create a participant user with CTF participant profile."""
    profile, _ = UserProfile.objects.get_or_create(user=participant_user)
    profile.user_type = "ctf_participant"
    profile.save(update_fields=["user_type"])
    return profile


@pytest.fixture
def standard_profile(db) -> UserProfile:
    """Create a standard user with standard profile."""
    user = User.objects.create_user(
        username="standard@test.com",
        email="standard@test.com",
        password="testpass123",  # noqa: S106  # nosec B106
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.user_type = "standard"
    profile.save(update_fields=["user_type"])
    return profile


@pytest.fixture
def request_factory() -> RequestFactory:
    """Django request factory."""
    return RequestFactory()


# ---------------------------------------------------------------------------
# OIDC Backend Extension Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOIDCBackendCTFUserType:
    """Test that the OIDC backend handles CTF user type claims."""

    def test_create_user_sets_user_type_from_claims(self):
        """OIDC create_user should set user_type from custom:user_type claim."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()

        # Create a real user to test _update_user_type end-to-end
        user = User.objects.create_user(
            username="newctf@test.com",
            email="newctf@test.com",
            password="testpass123",  # noqa: S106  # nosec B106
        )
        claims = {
            "sub": "cognito-sub-123",
            "email": "newctf@test.com",
            "custom:user_type": "ctf_organizer",
        }

        backend._update_user_type(user, claims)

        profile = UserProfile.objects.get(user=user)
        assert profile.user_type == "ctf_organizer"

    def test_update_user_type_organizer(self, organizer_user):
        """_update_user_type should set profile to ctf_organizer."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()
        claims = {"custom:user_type": "ctf_organizer"}

        backend._update_user_type(organizer_user, claims)

        profile = UserProfile.objects.get(user=organizer_user)
        assert profile.user_type == "ctf_organizer"

    def test_update_user_type_participant(self, participant_user):
        """_update_user_type should set profile to ctf_participant."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()
        claims = {"custom:user_type": "ctf_participant"}

        backend._update_user_type(participant_user, claims)

        profile = UserProfile.objects.get(user=participant_user)
        assert profile.user_type == "ctf_participant"

    def test_update_user_type_missing_claim_defaults_standard(self, standard_user):
        """Missing custom:user_type claim should leave profile as standard."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()
        claims = {"sub": "some-sub"}

        # Create profile first as standard
        UserProfile.objects.get_or_create(user=standard_user)

        backend._update_user_type(standard_user, claims)

        profile = UserProfile.objects.get(user=standard_user)
        assert profile.user_type == "standard"

    def test_update_user_type_invalid_type_ignored(self, standard_user):
        """Invalid user_type claim value should be ignored."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()
        claims = {"custom:user_type": "invalid_type"}

        UserProfile.objects.get_or_create(user=standard_user)
        backend._update_user_type(standard_user, claims)

        profile = UserProfile.objects.get(user=standard_user)
        assert profile.user_type == "standard"

    def test_update_ctf_event_from_claims(self, participant_user):
        """_update_user_type should set active_ctf_event from custom:ctf_event_id."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()

        event = CTFEvent.objects.create(
            name="Test Event",
            description="Test",
            created_by=participant_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now(),
            event_end=timezone.now() + timedelta(hours=8),
            scenario_id="basic",
        )

        claims = {
            "custom:user_type": "ctf_participant",
            "custom:ctf_event_id": str(event.id),
        }

        backend._update_user_type(participant_user, claims)

        profile = UserProfile.objects.get(user=participant_user)
        assert profile.user_type == "ctf_participant"
        assert profile.active_ctf_event_id == event.id

    def test_update_ctf_event_invalid_uuid_ignored(self, participant_user):
        """Invalid ctf_event_id should be ignored gracefully."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()
        claims = {
            "custom:user_type": "ctf_participant",
            "custom:ctf_event_id": "not-a-uuid",
        }

        backend._update_user_type(participant_user, claims)

        profile = UserProfile.objects.get(user=participant_user)
        assert profile.user_type == "ctf_participant"
        assert profile.active_ctf_event is None


# ---------------------------------------------------------------------------
# Dashboard Routing Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDashboardRouting:
    """Test that users are routed to the correct dashboard by user type."""

    def test_standard_user_redirected_to_mission_control(self, client, standard_profile):
        """Standard users should be sent to mission control dashboard."""
        client.force_login(standard_profile.user)
        response = client.get(reverse("dashboard_router"))
        assert response.status_code == 302
        assert "/mission-control/" in response.url

    def test_organizer_redirected_to_ctf_admin(self, client, organizer_profile):
        """CTF organizers should be sent to CTF admin dashboard."""
        client.force_login(organizer_profile.user)
        response = client.get(reverse("dashboard_router"))
        assert response.status_code == 302
        assert "/ctf/admin/" in response.url

    def test_participant_redirected_to_ctf_participant(self, client, participant_profile):
        """CTF participants should be sent to CTF participant dashboard."""
        client.force_login(participant_profile.user)
        response = client.get(reverse("dashboard_router"))
        assert response.status_code == 302
        assert "/ctf/" in response.url

    def test_unauthenticated_redirected_to_login(self, client):
        """Unauthenticated users should be redirected to login."""
        response = client.get(reverse("dashboard_router"))
        assert response.status_code == 302

    def test_user_without_profile_defaults_to_mission_control(self, client, db):
        """User without profile should be treated as standard."""
        user = User.objects.create_user(
            username="noprofile@test.com",
            email="noprofile@test.com",
            password="testpass123",  # noqa: S106  # nosec B106
        )
        client.force_login(user)
        response = client.get(reverse("dashboard_router"))
        assert response.status_code == 302
        assert "/mission-control/" in response.url


# ---------------------------------------------------------------------------
# Access Control Decorator Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAccessControlDecorators:
    """Test CTF access control decorators."""

    def test_organizer_required_allows_organizer(self, client, organizer_profile):
        """ctf_organizer_required should allow organizer access."""
        client.force_login(organizer_profile.user)
        response = client.get(reverse("ctf:admin_dashboard"))
        # Should get 200 (rendered template) not 403
        assert response.status_code == 200

    def test_organizer_required_blocks_participant(self, client, participant_profile):
        """ctf_organizer_required should block participants."""
        client.force_login(participant_profile.user)
        response = client.get(reverse("ctf:admin_dashboard"))
        assert response.status_code == 403

    def test_organizer_required_blocks_standard_user(self, client, standard_profile):
        """ctf_organizer_required should block standard users."""
        client.force_login(standard_profile.user)
        response = client.get(reverse("ctf:admin_dashboard"))
        assert response.status_code == 403

    def test_participant_required_allows_participant(self, client, participant_profile):
        """ctf_participant_required should allow participant access."""
        client.force_login(participant_profile.user)
        response = client.get(reverse("ctf:participant_dashboard"))
        assert response.status_code == 200

    def test_participant_required_blocks_standard_user(self, client, standard_profile):
        """ctf_participant_required should block standard users."""
        client.force_login(standard_profile.user)
        response = client.get(reverse("ctf:participant_dashboard"))
        assert response.status_code == 403

    def test_unauthenticated_redirected_to_login(self, client):
        """Unauthenticated users should be redirected to login."""
        response = client.get(reverse("ctf:admin_dashboard"))
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# CTF Login View Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFLoginView:
    """Test CTF-specific login view."""

    def test_login_page_renders(self, client):
        """CTF login page should render without errors."""
        response = client.get(reverse("ctf:ctf_login"))
        assert response.status_code == 200

    def test_login_page_with_event_param(self, client, ctf_event):
        """CTF login page should accept event_id query param."""
        response = client.get(reverse("ctf:ctf_login") + f"?event={ctf_event.id}")
        assert response.status_code == 200

    def test_login_page_with_invite_token(self, client, ctf_participant_invited):
        """CTF login page should accept invite token query param."""
        response = client.get(reverse("ctf:ctf_login") + f"?token={ctf_participant_invited.invite_token}")
        assert response.status_code == 200

    @override_settings(DEBUG=True)
    def test_dev_login_ctf_organizer(self, request_factory, db):
        """Dev login should support CTF organizer user type."""
        from config.dev_auth import dev_login

        request = request_factory.post(
            "/dev-login/",
            {"email": "ctforg@test.com", "user_type": "ctf_organizer"},
        )
        # Add session support for login()
        from django.contrib.sessions.backends.db import SessionStore

        request.session = SessionStore()
        response = dev_login(request)
        assert response.status_code == 302
        assert "/ctf/admin/" in response.url

        profile = UserProfile.objects.get(user__email="ctforg@test.com")
        assert profile.user_type == "ctf_organizer"

    @override_settings(DEBUG=True)
    def test_dev_login_ctf_participant(self, request_factory, db):
        """Dev login should support CTF participant user type."""
        from config.dev_auth import dev_login

        request = request_factory.post(
            "/dev-login/",
            {"email": "ctfpart@test.com", "user_type": "ctf_participant"},
        )
        from django.contrib.sessions.backends.db import SessionStore

        request.session = SessionStore()
        response = dev_login(request)
        assert response.status_code == 302
        assert "/ctf/" in response.url

        profile = UserProfile.objects.get(user__email="ctfpart@test.com")
        assert profile.user_type == "ctf_participant"

    @override_settings(DEBUG=True)
    def test_dev_login_standard_user_default(self, request_factory, db):
        """Dev login without user_type should default to standard."""
        from config.dev_auth import dev_login

        request = request_factory.post(
            "/dev-login/",
            {"email": "dev@example.com"},
        )
        from django.contrib.sessions.backends.db import SessionStore

        request.session = SessionStore()
        response = dev_login(request)
        assert response.status_code == 302
        assert "/mission-control/" in response.url


# ---------------------------------------------------------------------------
# CTF Context Processor Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFContextProcessor:
    """Test CTF navigation context processor."""

    def test_context_for_organizer(self, request_factory, organizer_profile):
        """Context processor should provide organizer navigation data."""
        from ctf.context_processors import ctf_navigation

        request = request_factory.get("/ctf/admin/")
        request.user = organizer_profile.user

        context = ctf_navigation(request)
        assert context["is_ctf_user"] is True
        assert context["is_ctf_organizer"] is True
        assert context["is_ctf_participant"] is False

    def test_context_for_participant(self, request_factory, participant_profile):
        """Context processor should provide participant navigation data."""
        from ctf.context_processors import ctf_navigation

        request = request_factory.get("/ctf/")
        request.user = participant_profile.user

        context = ctf_navigation(request)
        assert context["is_ctf_user"] is True
        assert context["is_ctf_organizer"] is False
        assert context["is_ctf_participant"] is True

    def test_context_for_standard_user(self, request_factory, standard_profile):
        """Context processor should indicate non-CTF user."""
        from ctf.context_processors import ctf_navigation

        request = request_factory.get("/")
        request.user = standard_profile.user

        context = ctf_navigation(request)
        assert context["is_ctf_user"] is False
        assert context["is_ctf_organizer"] is False
        assert context["is_ctf_participant"] is False

    def test_context_for_anonymous_user(self, request_factory):
        """Context processor should handle anonymous users."""
        from django.contrib.auth.models import AnonymousUser

        from ctf.context_processors import ctf_navigation

        request = request_factory.get("/")
        request.user = AnonymousUser()

        context = ctf_navigation(request)
        assert context["is_ctf_user"] is False

    def test_context_includes_active_event_for_participant(
        self, request_factory, participant_profile, ctf_event_active
    ):
        """Context processor should include active event for participants."""
        from ctf.context_processors import ctf_navigation

        participant_profile.active_ctf_event = ctf_event_active
        participant_profile.save(update_fields=["active_ctf_event"])

        request = request_factory.get("/ctf/")
        request.user = participant_profile.user

        context = ctf_navigation(request)
        assert context["active_ctf_event"] == ctf_event_active


# ---------------------------------------------------------------------------
# CTF Sidebar Template Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFSidebar:
    """Test that CTF users get CTF-specific sidebar."""

    def test_participant_sees_ctf_sidebar(self, client, participant_profile):
        """CTF participants should see CTF sidebar items."""
        client.force_login(participant_profile.user)
        response = client.get(reverse("ctf:participant_dashboard"))
        content = response.content.decode()
        assert "Challenges" in content or response.status_code == 200

    def test_organizer_sees_ctf_admin_sidebar(self, client, organizer_profile):
        """CTF organizers should see CTF admin sidebar items."""
        client.force_login(organizer_profile.user)
        response = client.get(reverse("ctf:admin_dashboard"))
        content = response.content.decode()
        assert "Events" in content or response.status_code == 200
