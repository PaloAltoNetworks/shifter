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

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory, override_settings
from django.urls import reverse

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


class TestCTFRegisterView:
    """The GET registration page hosts the fragment-token exchange.

    The invite token is carried in the URL fragment (#token=...) which browsers
    never send to the server, so this view reads no token, performs no login,
    and only renders the exchange page (SonarCloud S8435).
    """

    def test_get_renders_exchange_page(self, request_factory):
        """GET returns 200 and renders the exchange page without reading a token."""
        from django.contrib.auth.models import AnonymousUser

        from ctf.views import ctf_register

        request = request_factory.get("/ctf/register/")
        # AuthenticationMiddleware sets request.user in the real stack; this page
        # is OIDC-exempt and reached while unauthenticated.
        request.user = AnonymousUser()
        response = ctf_register(request)

        assert response.status_code == 200
        assert response["Referrer-Policy"] == "no-referrer"

    @patch("django.contrib.auth.login")
    def test_get_never_logs_in(self, mock_login, request_factory):
        """A token in the query string must be ignored: GET never authenticates."""
        from django.contrib.auth.models import AnonymousUser

        from ctf.views import ctf_register

        # Even if a token leaks into the query string, the GET page must not act on it.
        request = request_factory.get("/ctf/register/?token=should-be-ignored")
        request.user = AnonymousUser()
        response = ctf_register(request)

        assert response.status_code == 200
        mock_login.assert_not_called()


class TestCTFRegisterExchange:
    """The POST exchange consumes the invite token from the JSON body."""

    @staticmethod
    def _post(request_factory, token):
        return request_factory.post(
            "/ctf/register/exchange/",
            data=json.dumps({"token": token}),
            content_type="application/json",
        )

    @patch("django.contrib.auth.login")
    @patch("ctf.models.CTFParticipant.objects")
    def test_valid_token_logs_in_and_returns_redirect(self, mock_objects, mock_login, request_factory):
        """Valid token with linked user logs in and returns the participant range redirect."""
        from ctf.views import ctf_register_exchange

        mock_participant = MagicMock()
        mock_participant.user = _make_mock_user(email="part@test.com")
        mock_participant.is_invite_valid = True
        mock_objects.filter.return_value.select_related.return_value.first.return_value = mock_participant

        response = ctf_register_exchange(self._post(request_factory, "valid-token"))

        assert response.status_code == 200
        assert "/ctf/range/" in json.loads(response.content)["redirect"]
        mock_login.assert_called_once()

    @patch("django.contrib.auth.login")
    @patch("ctf.models.CTFParticipant.objects")
    def test_repeated_token_use_works(self, mock_objects, mock_login, request_factory):
        """Same token exchanged twice logs in both times (multi-use default)."""
        from ctf.views import ctf_register_exchange

        mock_participant = MagicMock()
        mock_participant.user = _make_mock_user(email="part@test.com")
        mock_participant.is_invite_valid = True
        mock_objects.filter.return_value.select_related.return_value.first.return_value = mock_participant

        for _ in range(2):
            response = ctf_register_exchange(self._post(request_factory, "valid-token"))
            assert response.status_code == 200
            assert "/ctf/range/" in json.loads(response.content)["redirect"]

    def test_missing_token_returns_400(self, request_factory):
        """Empty token returns a 400 JSON envelope."""
        from ctf.views import ctf_register_exchange

        response = ctf_register_exchange(self._post(request_factory, ""))
        assert response.status_code == 400
        assert "error" in json.loads(response.content)

    def test_absent_token_field_returns_400(self, request_factory):
        """A body without a token field returns a 400 JSON envelope."""
        from ctf.views import ctf_register_exchange

        request = request_factory.post(
            "/ctf/register/exchange/",
            data=json.dumps({}),
            content_type="application/json",
        )
        response = ctf_register_exchange(request)
        assert response.status_code == 400
        assert "error" in json.loads(response.content)

    def test_malformed_body_returns_400(self, request_factory):
        """A non-object / non-JSON body returns a 400 JSON envelope, not a 500."""
        from ctf.views import ctf_register_exchange

        request = request_factory.post(
            "/ctf/register/exchange/",
            data="not-json",
            content_type="application/json",
        )
        response = ctf_register_exchange(request)
        assert response.status_code == 400
        assert "error" in json.loads(response.content)

    def test_oversize_token_returns_400(self, request_factory):
        """A token far longer than any real invite token is rejected before any lookup."""
        from ctf.views import ctf_register_exchange

        response = ctf_register_exchange(self._post(request_factory, "x" * 4096))
        assert response.status_code == 400
        assert "error" in json.loads(response.content)

    @patch("ctf.models.CTFParticipant.objects")
    def test_invalid_token_returns_400(self, mock_objects, request_factory):
        """Unknown token returns 400."""
        from ctf.views import ctf_register_exchange

        mock_objects.filter.return_value.select_related.return_value.first.return_value = None

        response = ctf_register_exchange(self._post(request_factory, "bogus-token-value"))
        assert response.status_code == 400

    @patch("ctf.models.CTFParticipant.objects")
    def test_token_without_linked_user_returns_400(self, mock_objects, request_factory):
        """Token for a participant with no linked user returns 400."""
        from ctf.views import ctf_register_exchange

        mock_participant = MagicMock()
        mock_participant.user = None
        mock_objects.filter.return_value.select_related.return_value.first.return_value = mock_participant

        response = ctf_register_exchange(self._post(request_factory, "invited-token"))
        assert response.status_code == 400

    @patch("django.contrib.auth.login")
    @patch("ctf.models.CTFParticipant.objects")
    def test_expired_token_rejected(self, mock_objects, mock_login, request_factory):
        """Expired invite token returns 400 with an 'expired' message and no login."""
        from ctf.views import ctf_register_exchange

        mock_participant = MagicMock()
        mock_participant.user = _make_mock_user(email="expired@test.com")
        mock_participant.is_invite_valid = False
        mock_objects.filter.return_value.select_related.return_value.first.return_value = mock_participant

        response = ctf_register_exchange(self._post(request_factory, "expired-token"))
        assert response.status_code == 400
        assert "expired" in json.loads(response.content)["error"].lower()
        mock_login.assert_not_called()

    def test_token_never_echoed_in_error(self, request_factory):
        """An error response must not echo the submitted token value."""
        from ctf.views import ctf_register_exchange

        with patch("ctf.models.CTFParticipant.objects") as mock_objects:
            mock_objects.filter.return_value.select_related.return_value.first.return_value = None
            response = ctf_register_exchange(self._post(request_factory, "super-secret-token"))

        assert "super-secret-token" not in response.content.decode()

    @override_settings(MAGIC_LINK_SINGLE_USE=True)
    @patch("django.contrib.auth.login")
    @patch("ctf.models.CTFParticipant.objects")
    def test_single_use_clears_token(self, mock_objects, mock_login, request_factory):
        """When MAGIC_LINK_SINGLE_USE is True, the token is cleared after login."""
        from ctf.views import ctf_register_exchange

        mock_participant = MagicMock()
        mock_participant.user = _make_mock_user(email="single@test.com")
        mock_participant.is_invite_valid = True
        mock_objects.filter.return_value.select_related.return_value.first.return_value = mock_participant

        response = ctf_register_exchange(self._post(request_factory, "single-use-token"))
        assert response.status_code == 200
        mock_participant.save.assert_called_once()
        assert mock_participant.invite_token == ""

    def test_get_method_not_allowed(self, request_factory):
        """The exchange endpoint only accepts POST."""
        from ctf.views import ctf_register_exchange

        response = ctf_register_exchange(request_factory.get("/ctf/register/exchange/"))
        assert response.status_code == 405


class TestInviteRateLimit:
    """Test rate limiting on magic link generation endpoints (PLAT-101)."""

    def test_rate_limit_allows_within_limit(self):
        """Requests within limit should succeed."""
        from ctf.views._access import _check_invite_rate_limit

        with patch("django.core.cache.cache") as mock_cache:
            mock_cache.incr.return_value = 1
            assert _check_invite_rate_limit(user_id=1, limit=50) is True

    def test_rate_limit_blocks_over_limit(self):
        """Requests over limit should be blocked."""
        from ctf.views._access import _check_invite_rate_limit

        with patch("django.core.cache.cache") as mock_cache:
            mock_cache.incr.return_value = 51
            assert _check_invite_rate_limit(user_id=1, limit=50) is False


class TestCTFSidebar:
    """Test that CTF users get CTF-specific sidebar."""

    @pytest.mark.django_db
    def test_participant_sees_ctf_sidebar(self, client, ctf_participant, participant_user):
        """A registered CTF participant can reach the participant dashboard.

        Integration assertion (ADR-019): a real active CTFParticipant row makes
        the real ``is_active_participant`` gate admit the user, and the view
        renders for real — no first-party render/topology patches.
        """
        client.force_login(participant_user)
        response = client.get(reverse("ctf:participant_dashboard"))
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_organizer_sees_ctf_admin_sidebar(self, client, organizer_user):
        """A CTF organizer can reach the admin dashboard (real render)."""
        client.force_login(organizer_user)
        response = client.get(reverse("ctf:admin_dashboard"))
        assert response.status_code == 200


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

    @pytest.mark.django_db
    def test_dual_role_can_access_admin_views(self, client, django_user_model):
        """A user holding both roles can access organizer views.

        Integration assertion (ADR-019): a real user in both CTF groups reaches
        the real admin dashboard through the client, instead of patching
        first-party render/role topology.
        """
        from django.contrib.auth.models import Group

        user = django_user_model.objects.create_user(username="dual@test.com", email="dual@test.com")
        for group_name in (CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP):
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)

        client.force_login(user)
        response = client.get(reverse("ctf:admin_dashboard"))
        assert response.status_code == 200

    @patch("management.services.set_active_ctf_event")
    @patch("management.services.get_user_profile")
    @patch("django.contrib.auth.models.Group.objects")
    def test_adding_participant_does_not_remove_organizer(self, mock_group_objects, mock_get_profile, mock_set_event):
        """Registering as participant should not remove organizer group."""
        from ctf.services.participant.lifecycle import _set_ctf_participant_profile

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

    @pytest.mark.django_db
    def test_clearing_participant_does_not_remove_organizer(self, django_user_model):
        """Clearing a user's participant profile must not remove their organizer
        group: CTF Participant is platform-wide. Integration assertion (ADR-019):
        real user/groups/event/participant, no first-party seam patches (#1142).
        """
        from datetime import timedelta

        from django.contrib.auth.models import Group
        from django.utils import timezone

        from ctf.enums import EventStatus
        from ctf.models import CTFEvent, CTFParticipant
        from ctf.services.participant.lifecycle import _clear_ctf_participant_profile
        from management.services import set_active_ctf_event

        user = django_user_model.objects.create_user(username="org-part@test.com", email="org-part@test.com")
        for group_name in (CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP):
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)

        event = CTFEvent.objects.create(
            name="Solo Event",
            description="x",
            created_by=user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=2),
            event_end=timezone.now() + timedelta(hours=6),
            scenario_id="basic",
        )
        CTFParticipant.objects.create(
            event=event,
            user=user,
            email=user.email,
            name="P",
            status="active",
            registered_at=timezone.now(),
        )
        set_active_ctf_event(user, event.pk)

        # No OTHER eligible participation, so the participant group is removed —
        # but the organizer group must survive.
        _clear_ctf_participant_profile(user, event)

        assert user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
        assert not user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

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
