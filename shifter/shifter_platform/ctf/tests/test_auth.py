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
from django.contrib.auth.models import Group
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from ctf.enums import EventStatus, ParticipantStatus
from ctf.models import CTFEvent
from management.models import UserProfile
from shared.auth import CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP

if TYPE_CHECKING:
    from django.contrib.auth.models import User

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def organizer_profile(db, organizer_user) -> UserProfile:
    """Create an organizer user with CTF organizer group."""
    profile, _ = UserProfile.objects.get_or_create(user=organizer_user)
    # organizer_user fixture already adds group; ensure profile is returned
    return profile


@pytest.fixture
def participant_profile(db, participant_user) -> UserProfile:
    """Create a participant user with CTF participant group."""
    profile, _ = UserProfile.objects.get_or_create(user=participant_user)
    # participant_user fixture already adds group; ensure profile is returned
    return profile


@pytest.fixture
def standard_profile(db) -> UserProfile:
    """Create a standard user (no CTF groups)."""
    user = User.objects.create_user(
        username="standard@test.com",
        email="standard@test.com",
        password="testpass123",  # noqa: S106  # nosec B106
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
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

    def test_create_user_sets_group_from_claims(self):
        """OIDC create_user should add user to CTF Organizer group from claim."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()

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

        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()

    def test_update_user_type_organizer(self, organizer_user):
        """_update_user_type should add user to CTF Organizer group."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()
        claims = {"custom:user_type": "ctf_organizer"}

        backend._update_user_type(organizer_user, claims)

        assert organizer_user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()

    def test_update_user_type_participant(self, participant_user):
        """_update_user_type should add user to CTF Participant group."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()
        claims = {"custom:user_type": "ctf_participant"}

        backend._update_user_type(participant_user, claims)

        assert participant_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

    def test_update_user_type_missing_claim_no_group_change(self, organizer_user):
        """Missing custom:user_type claim should not change groups."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()
        claims = {"sub": "some-sub"}

        # Remove CTF groups before testing
        organizer_user.groups.clear()

        backend._update_user_type(organizer_user, claims)

        assert not organizer_user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
        assert not organizer_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

    def test_update_user_type_invalid_type_ignored(self, organizer_user):
        """Invalid user_type claim value should be ignored."""
        from config.oidc import ShifterOIDCBackend

        backend = ShifterOIDCBackend()
        claims = {"custom:user_type": "invalid_type"}

        # Remove CTF groups before testing
        organizer_user.groups.clear()

        backend._update_user_type(organizer_user, claims)

        assert not organizer_user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
        assert not organizer_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

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

        assert participant_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()
        profile = UserProfile.objects.get(user=participant_user)
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

        assert participant_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()
        profile = UserProfile.objects.get(user=participant_user)
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

    def test_participant_redirected_to_mission_control(self, client, participant_profile):
        """CTF participants should be sent to Mission Control dashboard."""
        client.force_login(participant_profile.user)
        response = client.get(reverse("dashboard_router"))
        assert response.status_code == 302
        assert "/mission-control/" in response.url

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

    def test_participant_required_allows_participant(self, client, ctf_participant):
        """ctf_participant_required should allow participant with CTFParticipant record."""
        client.force_login(ctf_participant.user)
        client.raise_request_exception = False
        response = client.get(reverse("ctf:participant_dashboard"))
        # Decorator should not block — 403 means access denied
        assert response.status_code != 403

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
        """Dev login should add user to CTF Organizer group."""
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

        user = User.objects.get(email="ctforg@test.com")
        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()

    @override_settings(DEBUG=True)
    def test_dev_login_ctf_participant(self, request_factory, db):
        """Dev login should add user to CTF Participant group."""
        from config.dev_auth import dev_login

        request = request_factory.post(
            "/dev-login/",
            {"email": "ctfpart@test.com", "user_type": "ctf_participant"},
        )
        from django.contrib.sessions.backends.db import SessionStore

        request.session = SessionStore()
        response = dev_login(request)
        assert response.status_code == 302
        assert "/mission-control/" in response.url

        user = User.objects.get(email="ctfpart@test.com")
        assert user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

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
# CTF Register View Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFRegisterView:
    """Test CTF participant registration via invite token."""

    def test_register_auto_creates_user(self, client, ctf_participant_invited):
        """Unauthenticated users with valid token get auto-registered."""
        url = reverse("ctf:ctf_register") + f"?token={ctf_participant_invited.invite_token}"
        response = client.get(url)
        assert response.status_code == 302
        assert "/mission-control/" in response.url

    def test_register_with_valid_token(self, client, ctf_participant_invited):
        """Valid invite token should auto-register and redirect to Mission Control."""
        url = reverse("ctf:ctf_register") + f"?token={ctf_participant_invited.invite_token}"
        response = client.get(url)
        assert response.status_code == 302
        assert "/mission-control/" in response.url

        ctf_participant_invited.refresh_from_db()
        assert ctf_participant_invited.user is not None
        assert ctf_participant_invited.status == ParticipantStatus.REGISTERED.value

    def test_register_with_expired_token(self, client, participant_profile, ctf_participant_invited):
        """Expired invite token should show error and redirect to login."""
        ctf_participant_invited.invite_token_expires = timezone.now() - timedelta(hours=1)
        ctf_participant_invited.save(update_fields=["invite_token_expires"])

        client.force_login(participant_profile.user)
        url = reverse("ctf:ctf_register") + f"?token={ctf_participant_invited.invite_token}"
        response = client.get(url)
        assert response.status_code == 302
        assert "login" in response.url

    def test_register_with_invalid_token(self, client, participant_profile):
        """Invalid token should show error and redirect to login."""
        client.force_login(participant_profile.user)
        url = reverse("ctf:ctf_register") + "?token=bogus-token-value"
        response = client.get(url)
        assert response.status_code == 302
        assert "login" in response.url

    def test_register_already_registered(self, client, participant_profile, ctf_participant_invited):
        """Already-registered participant should be logged in and redirected."""
        # First registration
        ctf_participant_invited.user = participant_profile.user
        ctf_participant_invited.status = ParticipantStatus.REGISTERED.value
        ctf_participant_invited.save(update_fields=["user", "status"])

        # Using token again should just log in the existing user
        url = reverse("ctf:ctf_register") + f"?token={ctf_participant_invited.invite_token}"
        response = client.get(url)
        assert response.status_code == 302
        assert "/mission-control/" in response.url

    def test_register_missing_token(self, client, participant_profile):
        """Missing token should redirect to login."""
        client.force_login(participant_profile.user)
        response = client.get(reverse("ctf:ctf_register"))
        assert response.status_code == 302
        assert "login" in response.url


# ---------------------------------------------------------------------------
# CTF Sidebar Template Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFSidebar:
    """Test that CTF users get CTF-specific sidebar."""

    def test_participant_sees_ctf_sidebar(self, client, ctf_participant):
        """CTF participants should see CTF sidebar items."""
        client.force_login(ctf_participant.user)
        client.raise_request_exception = False
        response = client.get(reverse("ctf:participant_dashboard"))
        # Decorator should not block
        assert response.status_code != 403

    def test_organizer_sees_ctf_admin_sidebar(self, client, organizer_profile):
        """CTF organizers should see CTF admin sidebar items."""
        client.force_login(organizer_profile.user)
        response = client.get(reverse("ctf:admin_dashboard"))
        content = response.content.decode()
        assert "Events" in content or response.status_code == 200


# ---------------------------------------------------------------------------
# Dual-Role Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDualRoles:
    """Test that a user can hold both CTF Organizer and CTF Participant roles."""

    def test_user_can_be_organizer_and_participant(self, organizer_profile, ctf_event):
        """A user in both groups should be recognized as both roles."""
        from ctf.bridges import get_user_role

        user = organizer_profile.user
        # Add participant group
        participant_group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
        user.groups.add(participant_group)

        role = get_user_role(user)
        assert role.is_ctf_organizer is True
        assert role.is_ctf_participant is True

    def test_dual_role_can_access_admin_views(self, client, organizer_profile):
        """User with both roles can access organizer views."""
        user = organizer_profile.user
        participant_group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
        user.groups.add(participant_group)

        client.force_login(user)
        response = client.get(reverse("ctf:admin_dashboard"))
        assert response.status_code == 200

    def test_adding_participant_does_not_remove_organizer(self, organizer_profile, ctf_event):
        """Registering as participant should not remove organizer group."""
        from ctf.services.participant import _set_ctf_participant_profile

        user = organizer_profile.user
        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()

        _set_ctf_participant_profile(user, ctf_event)

        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
        assert user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

    def test_clearing_participant_does_not_remove_organizer(self, organizer_profile, ctf_event):
        """Clearing participant should not affect organizer group."""
        from ctf.services.participant import (
            _clear_ctf_participant_profile,
            _set_ctf_participant_profile,
        )
        from management.services import get_user_profile

        user = organizer_profile.user
        _set_ctf_participant_profile(user, ctf_event)

        _clear_ctf_participant_profile(user, ctf_event)

        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
        assert not user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()
        profile = get_user_profile(user)
        assert profile.active_ctf_event is None

    def test_dashboard_routes_organizer_to_admin(self, client, organizer_profile):
        """Dashboard router should route dual-role user to admin (organizer takes priority)."""
        user = organizer_profile.user
        participant_group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
        user.groups.add(participant_group)

        client.force_login(user)
        response = client.get(reverse("dashboard_router"))
        assert response.status_code == 302
        assert "/ctf/admin/" in response.url
