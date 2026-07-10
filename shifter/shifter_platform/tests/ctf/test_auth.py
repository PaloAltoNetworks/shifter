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
from django.test import RequestFactory, override_settings
from django.urls import reverse

from shared.auth import (
    CTF_ORGANIZER_GROUP,
    CTF_PARTICIPANT_GROUP,
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


@pytest.mark.django_db
class TestOIDCBackendCTFUserType:
    """OIDC backend turns custom:user_type claims into CTF group membership.

    Behavior tests against real users, groups, and profiles through the
    backend's ``_update_user_type`` entry point. The sync mechanics (audit
    rows, add-only CTF membership, the CTF-only invariant) are unit-tested in
    ``tests/config/test_user_type_sync.py``; these tests cover the OIDC
    integration path and the ``custom:ctf_event_id`` plumbing.
    """

    def _make_backend(self):
        from config.oidc import ShifterOIDCBackend

        return ShifterOIDCBackend()

    @pytest.fixture
    def real_user(self, db):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(username="newctf@test.com", email="newctf@test.com")

    def test_organizer_claim_adds_organizer_group(self, real_user):
        self._make_backend()._update_user_type(real_user, {"custom:user_type": "ctf_organizer"})
        assert real_user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()

    def test_participant_claim_adds_participant_group(self, real_user):
        self._make_backend()._update_user_type(real_user, {"custom:user_type": "ctf_participant"})
        assert real_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

    def test_missing_claim_leaves_groups_unchanged(self, real_user):
        self._make_backend()._update_user_type(real_user, {"sub": "some-sub"})
        assert not real_user.groups.filter(name__in=[CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP]).exists()

    def test_invalid_claim_value_ignored(self, real_user):
        self._make_backend()._update_user_type(real_user, {"custom:user_type": "invalid_type"})
        assert not real_user.groups.filter(name__in=[CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP]).exists()

    def test_ctf_event_set_for_participant_from_claim(self, real_user):
        from datetime import timedelta

        from django.utils import timezone

        from ctf.enums import EventStatus
        from ctf.models import CTFEvent

        event = CTFEvent.objects.create(
            name="OIDC Event",
            description="event",
            created_by=real_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
        )

        self._make_backend()._update_user_type(
            real_user,
            {"custom:user_type": "ctf_participant", "custom:ctf_event_id": str(event.pk)},
        )

        real_user.refresh_from_db()
        assert real_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()
        assert real_user.profile.active_ctf_event_id == event.pk

    def test_invalid_ctf_event_id_ignored(self, real_user):
        self._make_backend()._update_user_type(
            real_user,
            {"custom:user_type": "ctf_participant", "custom:ctf_event_id": "not-a-uuid"},
        )
        real_user.refresh_from_db()
        assert real_user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()
        assert real_user.profile.active_ctf_event_id is None


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


class TestAccessControlDecorators:
    """Test CTF access control decorators."""

    def _make_view_request(self, request_factory, user, path="/test/"):
        """Create a request with user attached."""
        request = request_factory.get(path)
        request.user = user
        return request

    @pytest.mark.django_db
    def test_organizer_required_allows_organizer(self, client, organizer_user):
        """ctf_organizer_required should allow organizer access.

        Integration assertion (ADR-019): drive the real view through the test
        client with a real organizer user and real template render, rather than
        patching first-party ``render``/``get_user_role`` topology.
        """
        client.force_login(organizer_user)
        response = client.get(reverse("ctf:admin_dashboard"))
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

    @pytest.mark.django_db
    def test_participant_required_allows_participant(self, client, ctf_participant, participant_user):
        """ctf_participant_required should allow a registered participant.

        Integration assertion (ADR-019): a real active CTFParticipant row (the
        ``ctf_participant`` fixture) makes ``is_active_participant`` true, so the
        decorator admits the user and the view renders for real — no first-party
        ``is_active_participant``/``_get_active_participant``/``render`` patches.
        """
        client.force_login(participant_user)
        response = client.get(reverse("ctf:participant_dashboard"))
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


@pytest.mark.django_db
class TestDevLogin:
    """Dev login CTF user type support (behavior tests, real DB).

    Drives the dev-login view through the test client and asserts the real
    group membership and redirect. The shared sync mechanics and audit trail
    are unit-tested in ``tests/config/test_user_type_sync.py``.
    """

    @override_settings(DEBUG=True)
    def test_dev_login_ctf_organizer(self, client):
        """Dev login should add user to CTF Organizer group."""
        from django.contrib.auth import get_user_model

        response = client.post("/dev-login/", {"email": "ctforg@test.com", "user_type": "ctf_organizer"})

        assert response.status_code == 302
        assert "/ctf/admin/" in response.url
        user = get_user_model().objects.get(username="ctforg@test.com")
        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()

    @override_settings(DEBUG=True)
    def test_dev_login_ctf_participant(self, client):
        """Dev login should add user to CTF Participant group."""
        from django.contrib.auth import get_user_model

        response = client.post("/dev-login/", {"email": "ctfpart@test.com", "user_type": "ctf_participant"})

        assert response.status_code == 302
        assert "/mission-control/" in response.url
        user = get_user_model().objects.get(username="ctfpart@test.com")
        assert user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

    @override_settings(DEBUG=True)
    def test_dev_login_standard_user_default(self, client):
        """Dev login without user_type should default to standard (no CTF groups)."""
        from django.contrib.auth import get_user_model

        response = client.post("/dev-login/", {"email": "dev@example.com"})

        assert response.status_code == 302
        assert "/mission-control/" in response.url
        user = get_user_model().objects.get(username="dev@example.com")
        assert not user.groups.filter(name__in=[CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP]).exists()


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
