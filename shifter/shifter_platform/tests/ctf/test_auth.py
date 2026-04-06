"""Tests for CTF authentication, routing, and access control.

Tests cover:
- OIDC backend extension for CTF user types
- Dashboard routing by user type
- Access control decorators
- CTF magic link authentication
- CTF context processor
- Dev auth CTF user type support

All tests run WITHOUT @pytest.mark.django_db by mocking the ORM.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from shared.auth import (
    CTF_ORGANIZER_GROUP,
    CTF_PARTICIPANT_GROUP,
    THREAT_RESEARCH_GROUP,
    is_ctf_participant_only,
)

# ---------------------------------------------------------------------------
# Mock User Helpers
# ---------------------------------------------------------------------------


class _MockGroupManager:
    """Simulates user.groups with in-memory set for filter/add/remove/clear."""

    def __init__(self, group_names: set[str] | None = None):
        self._groups = set(group_names or ())

    def filter(self, *, name=None, name__in=None):
        """Return a queryset-like object for group filtering."""
        if name is not None:
            matched = {name} & self._groups
        elif name__in is not None:
            matched = set(name__in) & self._groups
        else:
            matched = set(self._groups)
        return _MockGroupQS(matched, self)

    def add(self, *groups):
        for g in groups:
            self._groups.add(g.name if hasattr(g, "name") else g)

    def remove(self, *groups):
        for g in groups:
            name = g.name if hasattr(g, "name") else g
            self._groups.discard(name)

    def clear(self):
        self._groups.clear()

    def values_list(self, field, flat=False):
        """Simulate values_list('name', flat=True)."""
        return list(self._groups)


class _MockGroupQS:
    """Mimics a filtered Group queryset."""

    def __init__(self, names: set[str], manager: _MockGroupManager):
        self._names = names
        self._manager = manager

    def exists(self):
        return bool(self._names)

    def __iter__(self):
        for n in self._names:
            yield _MockGroup(n)

    def __bool__(self):
        return bool(self._names)


class _MockGroup:
    """Minimal Group stand-in."""

    def __init__(self, name: str):
        self.name = name


def _make_mock_user(
    *,
    email: str = "test@test.com",
    groups: set[str] | None = None,
    is_active: bool = True,
    is_staff: bool = False,
    is_superuser: bool = False,
    is_authenticated: bool = True,
    pk: int = 1,
):
    """Create a mock user with in-memory group management."""
    user = MagicMock()
    user.pk = pk
    user.id = pk
    user.email = email
    user.username = email
    user.is_active = is_active
    user.is_staff = is_staff
    user.is_superuser = is_superuser
    user.is_authenticated = is_authenticated
    user.groups = _MockGroupManager(groups)
    return user


# ---------------------------------------------------------------------------
# Shared Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def request_factory() -> RequestFactory:
    """Django request factory."""
    return RequestFactory()


@pytest.fixture
def mock_organizer_user():
    """Mock user in CTF Organizer group."""
    return _make_mock_user(
        email="organizer@test.com",
        groups={CTF_ORGANIZER_GROUP},
        pk=10,
    )


@pytest.fixture
def mock_participant_user():
    """Mock user in CTF Participant group."""
    return _make_mock_user(
        email="participant@test.com",
        groups={CTF_PARTICIPANT_GROUP},
        pk=20,
    )


@pytest.fixture
def mock_standard_user():
    """Mock user with no CTF groups."""
    return _make_mock_user(
        email="standard@test.com",
        groups=set(),
        pk=30,
    )


@pytest.fixture
def mock_profile():
    """Reusable mock profile factory."""

    def _make(user_type="standard", active_ctf_event_id=None):
        profile = MagicMock()
        profile.user_type = user_type
        profile.active_ctf_event_id = active_ctf_event_id
        return profile

    return _make


# ---------------------------------------------------------------------------
# OIDC Backend Extension Tests
# ---------------------------------------------------------------------------


class TestOIDCBackendCTFUserType:
    """Test that the OIDC backend handles CTF user type claims."""

    def _make_backend(self):
        from config.oidc import ShifterOIDCBackend

        return ShifterOIDCBackend()

    @patch("config.oidc.Group.objects.get_or_create")
    @patch("config.oidc.get_user_profile")
    def test_create_user_sets_group_from_claims(self, mock_get_profile, mock_group_goc):
        """OIDC create_user should add user to CTF Organizer group from claim."""
        backend = self._make_backend()
        user = _make_mock_user(email="newctf@test.com")

        mock_group = _MockGroup(CTF_ORGANIZER_GROUP)
        mock_group_goc.return_value = (mock_group, True)

        profile = MagicMock(user_type="standard")
        mock_get_profile.return_value = profile

        claims = {
            "sub": "cognito-sub-123",
            "email": "newctf@test.com",
            "custom:user_type": "ctf_organizer",
        }

        backend._update_user_type(user, claims)

        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()

    @patch("config.oidc.Group.objects.get_or_create")
    @patch("config.oidc.get_user_profile")
    def test_update_user_type_organizer(self, mock_get_profile, mock_group_goc, mock_organizer_user):
        """_update_user_type should add user to CTF Organizer group."""
        backend = self._make_backend()

        mock_group = _MockGroup(CTF_ORGANIZER_GROUP)
        mock_group_goc.return_value = (mock_group, False)

        profile = MagicMock(user_type="ctf_organizer")
        mock_get_profile.return_value = profile

        claims = {"custom:user_type": "ctf_organizer"}
        backend._update_user_type(mock_organizer_user, claims)

        assert mock_organizer_user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()

    @patch("config.oidc.Group.objects.get_or_create")
    @patch("config.oidc.get_user_profile")
    def test_update_user_type_participant(self, mock_get_profile, mock_group_goc, mock_participant_user):
        """_update_user_type should add user to CTF Participant group."""
        backend = self._make_backend()

        mock_group = _MockGroup(CTF_PARTICIPANT_GROUP)
        mock_group_goc.return_value = (mock_group, False)

        profile = MagicMock(user_type="ctf_participant")
        mock_get_profile.return_value = profile

        claims = {"custom:user_type": "ctf_participant"}
        backend._update_user_type(mock_participant_user, claims)

        assert mock_participant_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

    def test_update_user_type_missing_claim_no_group_change(self, mock_organizer_user):
        """Missing custom:user_type claim should not change groups."""
        backend = self._make_backend()
        claims = {"sub": "some-sub"}

        mock_organizer_user.groups.clear()

        backend._update_user_type(mock_organizer_user, claims)

        assert not mock_organizer_user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
        assert not mock_organizer_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

    def test_update_user_type_invalid_type_ignored(self, mock_organizer_user):
        """Invalid user_type claim value should be ignored."""
        backend = self._make_backend()
        claims = {"custom:user_type": "invalid_type"}

        mock_organizer_user.groups.clear()

        backend._update_user_type(mock_organizer_user, claims)

        assert not mock_organizer_user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
        assert not mock_organizer_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

    @patch("management.services.set_active_ctf_event")
    @patch("ctf.models.CTFEvent.objects")
    @patch("config.oidc.Group.objects.get_or_create")
    @patch("config.oidc.get_user_profile")
    def test_update_ctf_event_from_claims(
        self, mock_get_profile, mock_group_goc, mock_event_objects, mock_set_event, mock_participant_user
    ):
        """_update_user_type should set active_ctf_event from custom:ctf_event_id."""
        backend = self._make_backend()

        mock_group = _MockGroup(CTF_PARTICIPANT_GROUP)
        mock_group_goc.return_value = (mock_group, False)

        mock_event = MagicMock()
        mock_event.pk = "11111111-1111-1111-1111-111111111111"
        mock_event_objects.filter.return_value.first.return_value = mock_event

        profile = MagicMock(user_type="ctf_participant", active_ctf_event_id=None)
        mock_get_profile.return_value = profile

        claims = {
            "custom:user_type": "ctf_participant",
            "custom:ctf_event_id": "11111111-1111-1111-1111-111111111111",
        }

        backend._update_user_type(mock_participant_user, claims)

        assert mock_participant_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()
        mock_set_event.assert_called_once_with(mock_participant_user, mock_event.pk)

    @patch("config.oidc.Group.objects.get_or_create")
    @patch("config.oidc.get_user_profile")
    def test_update_ctf_event_invalid_uuid_ignored(self, mock_get_profile, mock_group_goc, mock_participant_user):
        """Invalid ctf_event_id should be ignored gracefully."""
        backend = self._make_backend()

        mock_group = _MockGroup(CTF_PARTICIPANT_GROUP)
        mock_group_goc.return_value = (mock_group, False)

        profile = MagicMock(user_type="ctf_participant", active_ctf_event_id=None)
        mock_get_profile.return_value = profile

        claims = {
            "custom:user_type": "ctf_participant",
            "custom:ctf_event_id": "not-a-uuid",
        }

        backend._update_user_type(mock_participant_user, claims)

        assert mock_participant_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()
        # Invalid UUID should not trigger set_active_ctf_event
        assert profile.active_ctf_event_id is None


# ---------------------------------------------------------------------------
# Dashboard Routing Tests
# ---------------------------------------------------------------------------


class TestDashboardRouting:
    """Test that users are routed to the correct dashboard by user type."""

    def _call_dashboard_router(self, request_factory, user):
        """Call dashboard_router view directly with a mock user."""
        from config.views import dashboard_router

        request = request_factory.get("/dashboard/")
        request.user = user
        return dashboard_router(request)

    def test_standard_user_redirected_to_mission_control(self, request_factory, mock_standard_user):
        """Standard users should be sent to mission control dashboard."""
        response = self._call_dashboard_router(request_factory, mock_standard_user)
        assert response.status_code == 302
        assert "/mission-control/" in response.url

    def test_organizer_redirected_to_mission_control(self, request_factory, mock_organizer_user):
        """CTF organizers should be sent to Mission Control dashboard."""
        response = self._call_dashboard_router(request_factory, mock_organizer_user)
        assert response.status_code == 302
        assert "/mission-control/" in response.url

    def test_participant_redirected_to_mission_control(self, request_factory, mock_participant_user):
        """CTF participants should be sent to Mission Control dashboard."""
        response = self._call_dashboard_router(request_factory, mock_participant_user)
        assert response.status_code == 302
        assert "/mission-control/" in response.url

    def test_unauthenticated_redirected_to_login(self, request_factory):
        """Unauthenticated users should be redirected to login."""
        from config.views import dashboard_router

        anon = _make_mock_user(is_authenticated=False)
        request = request_factory.get("/dashboard/")
        request.user = anon
        response = dashboard_router(request)
        assert response.status_code == 302

    def test_user_without_profile_defaults_to_mission_control(self, request_factory):
        """User without profile should be treated as standard (no CTF groups)."""
        user = _make_mock_user(email="noprofile@test.com", groups=set(), pk=99)
        response = self._call_dashboard_router(request_factory, user)
        assert response.status_code == 302
        assert "/mission-control/" in response.url


# ---------------------------------------------------------------------------
# Access Control Decorator Tests
# ---------------------------------------------------------------------------


class TestAccessControlDecorators:
    """Test CTF access control decorators."""

    def _make_view_request(self, request_factory, user, path="/test/"):
        """Create a request with user attached."""
        request = request_factory.get(path)
        request.user = user
        return request

    def _mock_admin_dashboard_internals(self):
        """Return context managers for mocking admin_dashboard view internals."""
        return (
            patch("ctf.views.render", return_value=HttpResponse("ok", status=200)),
            patch("ctf.services.get_organizer_events", return_value=self._mock_event_qs()),
        )

    @staticmethod
    def _mock_event_qs():
        qs = MagicMock()
        qs.filter.return_value.count.return_value = 0
        qs.count.return_value = 0
        qs.__getitem__ = MagicMock(return_value=[])
        return qs

    @patch("management.services.get_user_profile")
    def test_organizer_required_allows_organizer(self, mock_get_profile, request_factory, mock_organizer_user):
        """ctf_organizer_required should allow organizer access."""
        from ctf.views import admin_dashboard

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)

        request = self._make_view_request(request_factory, mock_organizer_user)

        with (
            patch("ctf.views.render", return_value=HttpResponse("ok", status=200)),
            patch("ctf.services.get_organizer_events", return_value=self._mock_event_qs()),
        ):
            response = admin_dashboard(request)

        assert response.status_code == 200

    @patch("management.services.get_user_profile")
    def test_organizer_required_blocks_participant(self, mock_get_profile, request_factory, mock_participant_user):
        """ctf_organizer_required should block participants."""
        from ctf.views import admin_dashboard

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)

        request = self._make_view_request(request_factory, mock_participant_user)
        response = admin_dashboard(request)
        assert response.status_code == 403

    @patch("management.services.get_user_profile")
    def test_organizer_required_blocks_standard_user(self, mock_get_profile, request_factory, mock_standard_user):
        """ctf_organizer_required should block standard users."""
        from ctf.views import admin_dashboard

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)

        request = self._make_view_request(request_factory, mock_standard_user)
        response = admin_dashboard(request)
        assert response.status_code == 403

    @patch("ctf.models.CTFParticipant.objects")
    def test_participant_required_allows_participant(self, mock_objects, request_factory, mock_participant_user):
        """ctf_participant_required should allow participant with CTFParticipant record."""
        from ctf.views import participant_dashboard

        mock_objects.filter.return_value.exists.return_value = True

        request = self._make_view_request(request_factory, mock_participant_user)

        with (
            patch("ctf.views.render", return_value=HttpResponse("ok", status=200)),
            patch("ctf.services.participant.get_participant_by_user", return_value=None),
        ):
            response = participant_dashboard(request)

        assert response.status_code != 403

    @patch("ctf.models.CTFParticipant.objects")
    def test_participant_required_blocks_standard_user(self, mock_objects, request_factory, mock_standard_user):
        """ctf_participant_required should block standard users."""
        from ctf.views import participant_dashboard

        mock_objects.filter.return_value.exists.return_value = False

        request = self._make_view_request(request_factory, mock_standard_user)
        response = participant_dashboard(request)
        assert response.status_code == 403

    def test_unauthenticated_redirected_to_login(self, request_factory):
        """Unauthenticated users should be redirected to login."""
        from ctf.views import admin_dashboard

        anon = _make_mock_user(is_authenticated=False)
        request = request_factory.get("/ctf/admin/")
        request.user = anon
        response = admin_dashboard(request)
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Dev Login Tests
# ---------------------------------------------------------------------------


class TestDevLogin:
    """Test dev login CTF user type support."""

    @override_settings(DEBUG=True)
    @patch("config.dev_auth.get_user_profile")
    @patch("config.dev_auth.Group.objects.get_or_create")
    @patch("config.dev_auth.User.objects.get_or_create")
    @patch("config.dev_auth.login")
    def test_dev_login_ctf_organizer(
        self, mock_login, mock_user_goc, mock_group_goc, mock_get_profile, request_factory
    ):
        """Dev login should add user to CTF Organizer group."""
        from config.dev_auth import dev_login

        user = _make_mock_user(email="ctforg@test.com")
        mock_user_goc.return_value = (user, True)

        mock_group = _MockGroup(CTF_ORGANIZER_GROUP)
        mock_group_goc.return_value = (mock_group, True)

        mock_get_profile.return_value = MagicMock(user_type="standard")

        request = request_factory.post(
            "/dev-login/",
            {"email": "ctforg@test.com", "user_type": "ctf_organizer"},
        )
        request.session = {}
        response = dev_login(request)

        assert response.status_code == 302
        assert "/ctf/admin/" in response.url
        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()

    @override_settings(DEBUG=True)
    @patch("config.dev_auth.get_user_profile")
    @patch("config.dev_auth.Group.objects.get_or_create")
    @patch("config.dev_auth.User.objects.get_or_create")
    @patch("config.dev_auth.login")
    def test_dev_login_ctf_participant(
        self, mock_login, mock_user_goc, mock_group_goc, mock_get_profile, request_factory
    ):
        """Dev login should add user to CTF Participant group."""
        from config.dev_auth import dev_login

        user = _make_mock_user(email="ctfpart@test.com")
        mock_user_goc.return_value = (user, True)

        mock_group = _MockGroup(CTF_PARTICIPANT_GROUP)
        mock_group_goc.return_value = (mock_group, True)

        mock_get_profile.return_value = MagicMock(user_type="standard")

        request = request_factory.post(
            "/dev-login/",
            {"email": "ctfpart@test.com", "user_type": "ctf_participant"},
        )
        request.session = {}
        response = dev_login(request)

        assert response.status_code == 302
        assert "/mission-control/" in response.url
        assert user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

    @override_settings(DEBUG=True)
    @patch("config.dev_auth.get_user_profile")
    @patch("config.dev_auth.Group.objects.filter")
    @patch("config.dev_auth.User.objects.get_or_create")
    @patch("config.dev_auth.login")
    def test_dev_login_standard_user_default(
        self, mock_login, mock_user_goc, mock_group_filter, mock_get_profile, request_factory
    ):
        """Dev login without user_type should default to standard."""
        from config.dev_auth import dev_login

        user = _make_mock_user(email="dev@example.com")
        mock_user_goc.return_value = (user, True)

        mock_group_filter.return_value = []

        mock_get_profile.return_value = MagicMock(user_type="standard")

        request = request_factory.post(
            "/dev-login/",
            {"email": "dev@example.com"},
        )
        request.session = {}
        response = dev_login(request)

        assert response.status_code == 302
        assert "/mission-control/" in response.url


# ---------------------------------------------------------------------------
# CTF Context Processor Tests
# ---------------------------------------------------------------------------


class TestCTFContextProcessor:
    """Test CTF navigation context processor."""

    @patch("management.services.get_user_profile")
    def test_context_for_organizer(self, mock_get_profile, request_factory, mock_organizer_user):
        """Context processor should provide organizer navigation data."""
        from ctf.context_processors import ctf_navigation

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)

        request = request_factory.get("/ctf/admin/")
        request.user = mock_organizer_user

        context = ctf_navigation(request)
        assert context["is_ctf_user"] is True
        assert context["is_ctf_organizer"] is True
        assert context["is_ctf_participant"] is False

    @patch("management.services.get_user_profile")
    def test_context_for_participant(self, mock_get_profile, request_factory, mock_participant_user):
        """Context processor should provide participant navigation data."""
        from ctf.context_processors import ctf_navigation

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)

        request = request_factory.get("/ctf/")
        request.user = mock_participant_user

        context = ctf_navigation(request)
        assert context["is_ctf_user"] is True
        assert context["is_ctf_organizer"] is False
        assert context["is_ctf_participant"] is True

    @patch("management.services.get_user_profile")
    def test_context_for_standard_user(self, mock_get_profile, request_factory, mock_standard_user):
        """Context processor should indicate non-CTF user."""
        from ctf.context_processors import ctf_navigation

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)

        request = request_factory.get("/")
        request.user = mock_standard_user

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

    @patch("management.services.get_user_profile")
    @patch("ctf.models.CTFEvent.objects")
    def test_context_includes_active_event_for_participant(
        self, mock_event_objects, mock_get_profile, request_factory, mock_participant_user
    ):
        """Context processor should include active event for participants."""
        from uuid import uuid4

        from ctf.context_processors import ctf_navigation

        mock_event = MagicMock(name="Active Event")
        event_id = uuid4()
        mock_get_profile.return_value = MagicMock(active_ctf_event_id=event_id)
        mock_event_objects.filter.return_value.first.return_value = mock_event

        request = request_factory.get("/ctf/")
        request.user = mock_participant_user

        context = ctf_navigation(request)
        assert context["active_ctf_event"] == mock_event

    @patch("management.services.get_user_profile")
    def test_context_participant_only_true_for_pure_participant(
        self, mock_get_profile, request_factory, mock_participant_user
    ):
        """Pure CTF participant should have is_ctf_participant_only=True."""
        from ctf.context_processors import ctf_navigation

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)

        request = request_factory.get("/")
        request.user = mock_participant_user

        context = ctf_navigation(request)
        assert context["is_ctf_participant_only"] is True

    @patch("management.services.get_user_profile")
    def test_context_participant_only_false_for_staff_participant(
        self, mock_get_profile, request_factory, mock_participant_user
    ):
        """Staff user who is also a CTF participant should have is_ctf_participant_only=False."""
        from ctf.context_processors import ctf_navigation

        mock_participant_user.is_staff = True

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)

        request = request_factory.get("/")
        request.user = mock_participant_user

        context = ctf_navigation(request)
        assert context["is_ctf_participant_only"] is False

    @patch("management.services.get_user_profile")
    def test_context_participant_only_false_for_standard_user(
        self, mock_get_profile, request_factory, mock_standard_user
    ):
        """Standard (non-CTF) user should have is_ctf_participant_only=False."""
        from ctf.context_processors import ctf_navigation

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)

        request = request_factory.get("/")
        request.user = mock_standard_user

        context = ctf_navigation(request)
        assert context["is_ctf_participant_only"] is False


# ---------------------------------------------------------------------------
# is_ctf_participant_only Tests
# ---------------------------------------------------------------------------


class TestIsCtfParticipantOnly:
    """Test the is_ctf_participant_only() utility function."""

    def test_pure_participant_returns_true(self):
        """User with only CTF Participant group should return True."""
        user = _make_mock_user(groups={CTF_PARTICIPANT_GROUP})
        assert is_ctf_participant_only(user) is True

    def test_staff_participant_returns_false(self):
        """Staff user who is also a CTF participant should return False."""
        user = _make_mock_user(groups={CTF_PARTICIPANT_GROUP}, is_staff=True)
        assert is_ctf_participant_only(user) is False

    def test_superuser_participant_returns_false(self):
        """Superuser who is also a CTF participant should return False."""
        user = _make_mock_user(groups={CTF_PARTICIPANT_GROUP}, is_superuser=True)
        assert is_ctf_participant_only(user) is False

    def test_organizer_participant_returns_true(self):
        """User in both Organizer and Participant groups is still CTF-only (no Launch Range)."""
        user = _make_mock_user(groups={CTF_PARTICIPANT_GROUP, CTF_ORGANIZER_GROUP})
        assert is_ctf_participant_only(user) is True

    def test_threat_research_participant_returns_false(self):
        """User in both Threat Research and Participant groups should return False."""
        user = _make_mock_user(groups={CTF_PARTICIPANT_GROUP, THREAT_RESEARCH_GROUP})
        assert is_ctf_participant_only(user) is False

    def test_non_participant_returns_false(self):
        """User without CTF Participant group should return False."""
        user = _make_mock_user(groups=set())
        assert is_ctf_participant_only(user) is False

    def test_inactive_participant_returns_false(self):
        """Inactive user who is a CTF participant should return False."""
        user = _make_mock_user(groups={CTF_PARTICIPANT_GROUP}, is_active=False)
        assert is_ctf_participant_only(user) is False


# ---------------------------------------------------------------------------
# CTF Register View Tests
# ---------------------------------------------------------------------------


class TestCTFRegisterView:
    """Test CTF magic link authentication via invite token."""

    @patch("django.contrib.auth.login")
    @patch("ctf.models.CTFParticipant.objects")
    def test_valid_token_logs_in_and_redirects(self, mock_objects, mock_login, request_factory):
        """Valid token with linked user should log in and redirect to dashboard."""
        from ctf.views import ctf_register

        mock_user = _make_mock_user(email="part@test.com")
        mock_participant = MagicMock()
        mock_participant.user = mock_user
        mock_participant.is_invite_valid = True
        mock_objects.filter.return_value.select_related.return_value.first.return_value = mock_participant

        request = request_factory.get("/ctf/register/?token=valid-token")
        response = ctf_register(request)

        assert response.status_code == 302
        assert "/mission-control/" in response.url
        mock_login.assert_called_once()

    @patch("django.contrib.auth.login")
    @patch("ctf.models.CTFParticipant.objects")
    def test_repeated_token_use_works(self, mock_objects, mock_login, request_factory):
        """Using the same token again should log in the same user (multi-use default)."""
        from ctf.views import ctf_register

        mock_user = _make_mock_user(email="part@test.com")
        mock_participant = MagicMock()
        mock_participant.user = mock_user
        mock_participant.is_invite_valid = True
        mock_objects.filter.return_value.select_related.return_value.first.return_value = mock_participant

        # First use
        request = request_factory.get("/ctf/register/?token=valid-token")
        response = ctf_register(request)
        assert response.status_code == 302
        assert "/mission-control/" in response.url

        # Second use
        request = request_factory.get("/ctf/register/?token=valid-token")
        response = ctf_register(request)
        assert response.status_code == 302
        assert "/mission-control/" in response.url

    def test_missing_token_returns_400(self, request_factory):
        """Missing token should return 400."""
        from ctf.views import ctf_register

        request = request_factory.get("/ctf/register/")
        response = ctf_register(request)
        assert response.status_code == 400

    @patch("ctf.models.CTFParticipant.objects")
    def test_invalid_token_returns_400(self, mock_objects, request_factory):
        """Invalid token should return 400."""
        from ctf.views import ctf_register

        mock_objects.filter.return_value.select_related.return_value.first.return_value = None

        request = request_factory.get("/ctf/register/?token=bogus-token-value")
        response = ctf_register(request)
        assert response.status_code == 400

    @patch("ctf.models.CTFParticipant.objects")
    def test_token_without_linked_user_returns_400(self, mock_objects, request_factory):
        """Token for participant with no linked user should return 400."""
        from ctf.views import ctf_register

        mock_participant = MagicMock()
        mock_participant.user = None
        mock_objects.filter.return_value.select_related.return_value.first.return_value = mock_participant

        request = request_factory.get("/ctf/register/?token=invited-token")
        response = ctf_register(request)
        assert response.status_code == 400

    @patch("django.contrib.auth.login")
    @patch("ctf.models.CTFParticipant.objects")
    def test_expired_token_rejected(self, mock_objects, mock_login, request_factory):
        """Expired invite token should return 400."""
        from ctf.views import ctf_register

        mock_participant = MagicMock()
        mock_participant.user = _make_mock_user(email="expired@test.com")
        mock_participant.is_invite_valid = False
        mock_objects.filter.return_value.select_related.return_value.first.return_value = mock_participant

        request = request_factory.get("/ctf/register/?token=expired-token")
        response = ctf_register(request)
        assert response.status_code == 400
        assert b"expired" in response.content.lower()
        mock_login.assert_not_called()

    @patch("django.contrib.auth.login")
    @patch("ctf.models.CTFParticipant.objects")
    def test_valid_token_checks_expiration(self, mock_objects, mock_login, request_factory):
        """Valid token should pass the is_invite_valid check and log in."""
        from ctf.views import ctf_register

        mock_participant = MagicMock()
        mock_participant.user = _make_mock_user(email="valid@test.com")
        mock_participant.is_invite_valid = True
        mock_objects.filter.return_value.select_related.return_value.first.return_value = mock_participant

        request = request_factory.get("/ctf/register/?token=valid-token")
        response = ctf_register(request)
        assert response.status_code == 302
        mock_login.assert_called_once()

    @override_settings(MAGIC_LINK_SINGLE_USE=True)
    @patch("django.contrib.auth.login")
    @patch("ctf.models.CTFParticipant.objects")
    def test_single_use_clears_token(self, mock_objects, mock_login, request_factory):
        """When MAGIC_LINK_SINGLE_USE is True, token is cleared after login."""
        from ctf.views import ctf_register

        mock_participant = MagicMock()
        mock_participant.user = _make_mock_user(email="single@test.com")
        mock_participant.is_invite_valid = True
        mock_objects.filter.return_value.select_related.return_value.first.return_value = mock_participant

        request = request_factory.get("/ctf/register/?token=single-use-token")
        response = ctf_register(request)
        assert response.status_code == 302
        mock_participant.save.assert_called_once()
        assert mock_participant.invite_token == ""


class TestInviteRateLimit:
    """Test rate limiting on magic link generation endpoints (PLAT-101)."""

    def test_rate_limit_allows_within_limit(self):
        """Requests within limit should succeed."""
        from ctf.views import _check_invite_rate_limit

        with patch("django.core.cache.cache") as mock_cache:
            mock_cache.incr.return_value = 1
            assert _check_invite_rate_limit(user_id=1, limit=50) is True

    def test_rate_limit_blocks_over_limit(self):
        """Requests over limit should be blocked."""
        from ctf.views import _check_invite_rate_limit

        with patch("django.core.cache.cache") as mock_cache:
            mock_cache.incr.return_value = 51
            assert _check_invite_rate_limit(user_id=1, limit=50) is False


# ---------------------------------------------------------------------------
# CTF Sidebar Template Tests
# ---------------------------------------------------------------------------


class TestCTFSidebar:
    """Test that CTF users get CTF-specific sidebar."""

    @patch("ctf.models.CTFParticipant.objects")
    @patch("ctf.views.render")
    def test_participant_sees_ctf_sidebar(self, mock_render, mock_objects, request_factory, mock_participant_user):
        """CTF participants should see CTF sidebar items."""
        from ctf.views import participant_dashboard

        mock_objects.filter.return_value.exists.return_value = True
        mock_render.return_value = HttpResponse("ok", status=200)

        request = request_factory.get("/ctf/participant/dashboard/")
        request.user = mock_participant_user

        with patch("ctf.services.participant.get_participant_by_user", return_value=None):
            response = participant_dashboard(request)

        assert response.status_code != 403

    @patch("management.services.get_user_profile")
    @patch("ctf.views.render")
    def test_organizer_sees_ctf_admin_sidebar(
        self, mock_render, mock_get_profile, request_factory, mock_organizer_user
    ):
        """CTF organizers should see CTF admin sidebar items."""
        from ctf.views import admin_dashboard

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)
        mock_render.return_value = HttpResponse("ok", status=200)

        request = request_factory.get("/ctf/admin/")
        request.user = mock_organizer_user

        with patch("ctf.services.get_organizer_events") as mock_events:
            mock_qs = MagicMock()
            mock_qs.filter.return_value.count.return_value = 0
            mock_qs.count.return_value = 0
            mock_qs.__getitem__ = MagicMock(return_value=[])
            mock_events.return_value = mock_qs
            response = admin_dashboard(request)

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Dual-Role Tests
# ---------------------------------------------------------------------------


class TestDualRoles:
    """Test that a user can hold both CTF Organizer and CTF Participant roles."""

    @patch("ctf.models.CTFEvent.objects")
    @patch("management.services.get_user_profile")
    def test_user_can_be_organizer_and_participant(self, mock_get_profile, mock_event_objects):
        """A user in both groups should be recognized as both roles."""
        from uuid import uuid4

        from ctf.bridges import get_user_role

        user = _make_mock_user(
            email="dual@test.com",
            groups={CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP},
        )

        event_id = uuid4()
        mock_event = MagicMock()
        mock_get_profile.return_value = MagicMock(active_ctf_event_id=event_id)
        mock_event_objects.filter.return_value.first.return_value = mock_event

        role = get_user_role(user)
        assert role.is_ctf_organizer is True
        assert role.is_ctf_participant is True

    @patch("management.services.get_user_profile")
    @patch("ctf.views.render")
    def test_dual_role_can_access_admin_views(self, mock_render, mock_get_profile, request_factory):
        """User with both roles can access organizer views."""
        from ctf.views import admin_dashboard

        user = _make_mock_user(
            email="dual@test.com",
            groups={CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP},
        )

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)
        mock_render.return_value = HttpResponse("ok", status=200)

        request = request_factory.get("/ctf/admin/")
        request.user = user

        with patch("ctf.services.get_organizer_events") as mock_events:
            mock_qs = MagicMock()
            mock_qs.filter.return_value.count.return_value = 0
            mock_qs.count.return_value = 0
            mock_qs.__getitem__ = MagicMock(return_value=[])
            mock_events.return_value = mock_qs
            response = admin_dashboard(request)

        assert response.status_code == 200

    @patch("management.services.set_active_ctf_event")
    @patch("management.services.get_user_profile")
    @patch("django.contrib.auth.models.Group.objects")
    def test_adding_participant_does_not_remove_organizer(self, mock_group_objects, mock_get_profile, mock_set_event):
        """Registering as participant should not remove organizer group."""
        from ctf.services.participant import _set_ctf_participant_profile

        user = _make_mock_user(
            email="org@test.com",
            groups={CTF_ORGANIZER_GROUP},
        )

        mock_group = _MockGroup(CTF_PARTICIPANT_GROUP)
        mock_group_objects.get_or_create.return_value = (mock_group, True)

        mock_event = MagicMock()
        mock_event.pk = "event-uuid"

        mock_get_profile.return_value = MagicMock(active_ctf_event_id=None)

        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()

        _set_ctf_participant_profile(user, mock_event)

        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
        assert user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()
        mock_set_event.assert_called_once_with(user, mock_event.pk)

    @patch("management.services.set_active_ctf_event")
    @patch("management.services.get_user_profile")
    @patch("django.contrib.auth.models.Group.objects")
    def test_clearing_participant_does_not_remove_organizer(self, mock_group_objects, mock_get_profile, mock_set_event):
        """Clearing participant should not affect organizer group."""
        from ctf.services.participant import (
            _clear_ctf_participant_profile,
            _set_ctf_participant_profile,
        )

        user = _make_mock_user(
            email="org@test.com",
            groups={CTF_ORGANIZER_GROUP},
        )

        mock_group = _MockGroup(CTF_PARTICIPANT_GROUP)
        mock_group_objects.get_or_create.return_value = (mock_group, True)
        mock_group_objects.filter.return_value.first.return_value = mock_group

        mock_event = MagicMock()
        mock_event.pk = "event-uuid"

        profile = MagicMock()
        profile.active_ctf_event_id = "event-uuid"
        mock_get_profile.return_value = profile

        # First set the participant profile (adds participant group)
        _set_ctf_participant_profile(user, mock_event)

        # Clear the participant profile
        _clear_ctf_participant_profile(user, mock_event)

        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
        assert not user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()
        # set_active_ctf_event called with None on clear
        mock_set_event.assert_any_call(user, None)

    def test_dashboard_routes_organizer_to_mission_control(self, request_factory):
        """Dashboard router should route dual-role user to Mission Control."""
        from config.views import dashboard_router

        user = _make_mock_user(
            email="dual@test.com",
            groups={CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP},
        )

        request = request_factory.get("/dashboard/")
        request.user = user
        response = dashboard_router(request)

        assert response.status_code == 302
        assert "/mission-control/" in response.url
