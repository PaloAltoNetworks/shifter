"""Tests for organizer ownership checks on all CTF admin views.

Verifies that organizer views and APIs return 403 when an organizer
attempts to access an event they do not own, and 200 when the owner accesses.

All tests run WITHOUT @pytest.mark.django_db by mocking the ORM.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class _MockGroupManager:
    """Simulates user.groups with in-memory set for filter/add/remove/clear."""

    def __init__(self, group_names: set[str] | None = None):
        self._groups = set(group_names or ())

    def filter(self, *, name=None, name__in=None):
        if name is not None:
            matched = {name} & self._groups
        elif name__in is not None:
            matched = set(name__in) & self._groups
        else:
            matched = set(self._groups)
        return _MockGroupQS(matched)

    def values_list(self, field, flat=False):
        return list(self._groups)


class _MockGroupQS:
    """Mimics a filtered Group queryset."""

    def __init__(self, names: set[str]):
        self._names = names

    def exists(self):
        return bool(self._names)

    def __iter__(self):
        for n in self._names:
            yield MagicMock(name=n)

    def __bool__(self):
        return bool(self._names)


def _make_mock_user(*, pk: int = 1, email: str = "test@test.com", groups: set[str] | None = None):
    """Create a mock user with in-memory group management."""
    user = MagicMock()
    user.pk = pk
    user.id = pk
    user.email = email
    user.username = email
    user.is_active = True
    user.is_staff = False
    user.is_superuser = False
    user.is_authenticated = True
    user.groups = _MockGroupManager(groups)
    return user


@dataclass(frozen=True)
class _MockUserRole:
    is_ctf_organizer: bool = False
    is_ctf_participant: bool = False
    active_ctf_event: object | None = None


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

EVENT_ID = uuid.uuid4()
OWNER_PK = 10
NON_OWNER_PK = 20


@pytest.fixture
def rf() -> RequestFactory:
    return RequestFactory()


@pytest.fixture
def mock_owner_user():
    """Mock user who owns the event."""
    from shared.auth import CTF_ORGANIZER_GROUP

    return _make_mock_user(pk=OWNER_PK, email="owner@test.com", groups={CTF_ORGANIZER_GROUP})


@pytest.fixture
def mock_non_owner_user():
    """Mock user who is an organizer but does NOT own the event."""
    from shared.auth import CTF_ORGANIZER_GROUP

    return _make_mock_user(pk=NON_OWNER_PK, email="other@test.com", groups={CTF_ORGANIZER_GROUP})


@pytest.fixture
def mock_event():
    """Mock CTFEvent owned by OWNER_PK."""
    event = MagicMock()
    event.id = EVENT_ID
    event.pk = EVENT_ID
    event.created_by_id = OWNER_PK
    event.name = "Test CTF Event"
    event.status = "scheduled"
    event.team_mode = False
    event.scenario_id = "basic"
    return event


@pytest.fixture
def _patch_get_event(mock_event):
    """Patch ctf.services.get_event to return mock_event."""
    with patch("ctf.services.get_event", return_value=mock_event) as m:
        yield m


@pytest.fixture
def _patch_role_organizer():
    """Patch get_user_role to return organizer role."""
    role = _MockUserRole(is_ctf_organizer=True)
    with patch("ctf.views.get_user_role", return_value=role):
        yield


@pytest.fixture
def _patch_render():
    """Patch ctf.views.render to return a plain 200 response (skip template/context processors)."""
    with patch("ctf.views.render", return_value=HttpResponse("ok", status=200)) as m:
        yield m


# ---------------------------------------------------------------------------
# Helper to build an authenticated request
# ---------------------------------------------------------------------------


def _get_request(rf: RequestFactory, user, path: str = "/fake/", method: str = "get", **kwargs):
    """Build a request with the given user attached."""
    factory_method = getattr(rf, method)
    request = factory_method(path, **kwargs)
    request.user = user
    return request


# ===========================================================================
# Admin HTML views — non-owner gets 403
# ===========================================================================


@pytest.mark.usefixtures("_patch_get_event", "_patch_role_organizer")
class TestAdminViewOwnershipChecks:
    """Verify HTML admin views reject non-owning organizers with 403."""

    def test_range_list_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import admin_range_list

        request = _get_request(rf, mock_non_owner_user)
        response = admin_range_list(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_notification_list_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import admin_notification_list

        request = _get_request(rf, mock_non_owner_user)
        response = admin_notification_list(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_notification_create_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import admin_notification_create

        request = _get_request(rf, mock_non_owner_user)
        response = admin_notification_create(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_team_list_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import admin_team_list

        request = _get_request(rf, mock_non_owner_user)
        response = admin_team_list(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_scoreboard_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import admin_scoreboard

        request = _get_request(rf, mock_non_owner_user)
        response = admin_scoreboard(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_analytics_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import admin_analytics

        request = _get_request(rf, mock_non_owner_user)
        response = admin_analytics(request, event_id=EVENT_ID)
        assert response.status_code == 403


# ===========================================================================
# API views — non-owner gets 403
# ===========================================================================


@pytest.mark.usefixtures("_patch_get_event", "_patch_role_organizer")
class TestAPIOwnershipChecks:
    """Verify API endpoints reject non-owning organizers with 403."""

    def test_api_event_detail_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import api_event_detail

        request = _get_request(rf, mock_non_owner_user)
        response = api_event_detail(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_api_notification_list_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import api_notification_list

        request = _get_request(rf, mock_non_owner_user)
        response = api_notification_list(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_api_notification_send_denies_other_organizer(self, rf, mock_non_owner_user, mock_event):
        from ctf.views import api_notification_send

        notif_id = uuid.uuid4()
        mock_notif = MagicMock()
        mock_notif.id = notif_id
        mock_notif.pk = notif_id
        mock_notif.event = mock_event
        mock_notif.event_id = mock_event.id

        mock_qs = MagicMock()
        mock_qs.filter.return_value.first.return_value = mock_notif

        with patch("ctf.models.CTFNotification.objects") as mock_objects:
            mock_objects.select_related.return_value = mock_qs
            request = _get_request(rf, mock_non_owner_user, method="post")
            response = api_notification_send(request, notification_id=notif_id)

        assert response.status_code == 403

    def test_api_range_list_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import api_range_list

        request = _get_request(rf, mock_non_owner_user)
        response = api_range_list(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_api_provision_ranges_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import api_provision_ranges

        request = _get_request(rf, mock_non_owner_user, method="post")
        response = api_provision_ranges(request, event_id=EVENT_ID)
        assert response.status_code == 403


# ===========================================================================
# Owner CAN access — verify 200 (not just that others can't)
# ===========================================================================


@pytest.mark.usefixtures("_patch_get_event", "_patch_role_organizer", "_patch_render")
class TestOwnerCanAccess:
    """Verify the owning organizer CAN access these views (not just that others can't)."""

    def test_range_list_allows_owner(self, rf, mock_owner_user):
        from ctf.views import admin_range_list

        with patch("ctf.models.CTFParticipant.objects") as mock_objects:
            mock_objects.filter.return_value.order_by.return_value = []
            request = _get_request(rf, mock_owner_user)
            response = admin_range_list(request, event_id=EVENT_ID)

        assert response.status_code == 200

    def test_notification_list_allows_owner(self, rf, mock_owner_user):
        from ctf.views import admin_notification_list

        with patch("ctf.models.CTFNotification.objects") as mock_objects:
            mock_objects.filter.return_value.order_by.return_value = []
            request = _get_request(rf, mock_owner_user)
            response = admin_notification_list(request, event_id=EVENT_ID)

        assert response.status_code == 200

    def test_notification_create_allows_owner(self, rf, mock_owner_user):
        from ctf.views import admin_notification_create

        request = _get_request(rf, mock_owner_user)
        response = admin_notification_create(request, event_id=EVENT_ID)
        assert response.status_code == 200

    def test_api_range_list_allows_owner(self, rf, mock_owner_user):
        from ctf.views import api_range_list

        with patch("ctf.models.CTFParticipant.objects") as mock_objects:
            mock_objects.filter.return_value.order_by.return_value = []
            request = _get_request(rf, mock_owner_user)
            response = api_range_list(request, event_id=EVENT_ID)

        assert response.status_code == 200

    def test_api_notification_list_allows_owner(self, rf, mock_owner_user):
        from ctf.views import api_notification_list

        with patch("ctf.models.CTFNotification.objects") as mock_objects:
            mock_objects.filter.return_value.order_by.return_value = []
            request = _get_request(rf, mock_owner_user)
            response = api_notification_list(request, event_id=EVENT_ID)

        assert response.status_code == 200
