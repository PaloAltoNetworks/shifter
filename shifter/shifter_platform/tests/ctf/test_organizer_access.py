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
    event.status = "registration"
    event.team_mode = False
    event.scenario_id = "basic"
    event.scoreboard_visible = True
    event.is_scoreboard_frozen = False
    event.scoreboard_freeze_at = None
    return event


@pytest.fixture
def mock_participant_user():
    """Mock user who is a CTF participant (not an organizer)."""
    from shared.auth import CTF_PARTICIPANT_GROUP

    return _make_mock_user(pk=30, email="participant@test.com", groups={CTF_PARTICIPANT_GROUP})


@pytest.fixture
def _patch_role_participant():
    """Patch get_user_role to return participant role."""
    role = _MockUserRole(is_ctf_participant=True)
    with patch("ctf.views.get_user_role", return_value=role):
        yield


@pytest.fixture
def _patch_no_brackets():
    """Patch _resolve_bracket_filter to return empty bracket list (no DB)."""
    with patch("ctf.views._resolve_bracket_filter", return_value=([], None, None)):
        yield


@pytest.fixture
def _patch_empty_scoreboard():
    """Patch the scoreboard data accessors to return empty rankings (no DB)."""
    with (
        patch("ctf.services.scoring.get_scoreboard", return_value=[]),
        patch("ctf.services.scoring.get_team_scoreboard", return_value=[]),
    ):
        yield


@pytest.fixture
def _patch_participant_membership_true():
    """Patch `is_active_participant` to report a non-disqualified hit.

    Both call sites (`api_scoreboard`, `api_file_download`) import the
    helper locally at function entry, so patching at source
    (`ctf.services.participant.is_active_participant`) intercepts both.
    """
    with patch("ctf.services.participant.is_active_participant", return_value=True) as m:
        yield m


@pytest.fixture
def _patch_participant_membership_false():
    """Patch `is_active_participant` to report no membership."""
    with patch("ctf.services.participant.is_active_participant", return_value=False) as m:
        yield m


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


# ===========================================================================
# Issue #765 — challenge JSON APIs reject other organizers
# ===========================================================================


@pytest.mark.usefixtures("_patch_get_event", "_patch_role_organizer")
class TestAPIChallengeOwnershipChecks:
    """Verify api_challenge_list and api_challenge_detail reject non-owners with 403.

    Backstops the existing view-level _check_event_ownership call (defense
    in depth) and proves the documented contract on the JSON endpoints.
    """

    def test_api_challenge_list_get_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import api_challenge_list

        request = _get_request(rf, mock_non_owner_user)
        response = api_challenge_list(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_api_challenge_list_post_denies_other_organizer(self, rf, mock_non_owner_user):
        from ctf.views import api_challenge_list

        request = _get_request(
            rf,
            mock_non_owner_user,
            method="post",
            data="{}",
            content_type="application/json",
        )
        response = api_challenge_list(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_api_challenge_detail_get_denies_other_organizer(self, rf, mock_non_owner_user, mock_event):
        from ctf.views import api_challenge_detail

        challenge_id = uuid.uuid4()
        mock_challenge = MagicMock()
        mock_challenge.id = challenge_id
        mock_challenge.event = mock_event
        mock_challenge.event_id = mock_event.id

        with patch("ctf.services.get_challenge", return_value=mock_challenge):
            request = _get_request(rf, mock_non_owner_user)
            response = api_challenge_detail(request, challenge_id=challenge_id)
        assert response.status_code == 403

    def test_api_challenge_detail_put_denies_other_organizer(self, rf, mock_non_owner_user, mock_event):
        from ctf.views import api_challenge_detail

        challenge_id = uuid.uuid4()
        mock_challenge = MagicMock()
        mock_challenge.id = challenge_id
        mock_challenge.event = mock_event
        mock_challenge.event_id = mock_event.id

        with patch("ctf.services.get_challenge", return_value=mock_challenge):
            request = _get_request(
                rf,
                mock_non_owner_user,
                method="put",
                data="{}",
                content_type="application/json",
            )
            response = api_challenge_detail(request, challenge_id=challenge_id)
        assert response.status_code == 403

    def test_api_challenge_detail_delete_denies_other_organizer(self, rf, mock_non_owner_user, mock_event):
        from ctf.views import api_challenge_detail

        challenge_id = uuid.uuid4()
        mock_challenge = MagicMock()
        mock_challenge.id = challenge_id
        mock_challenge.event = mock_event
        mock_challenge.event_id = mock_event.id

        with patch("ctf.services.get_challenge", return_value=mock_challenge):
            request = _get_request(rf, mock_non_owner_user, method="delete")
            response = api_challenge_detail(request, challenge_id=challenge_id)
        assert response.status_code == 403


# ===========================================================================
# Issue #768 — api_scoreboard rejects unrelated organizers / participants
# ===========================================================================


class TestAPIScoreboardAuthorization:
    """Verify api_scoreboard authorizes by event ownership or participant assignment.

    Before this fix, any user with any CTF role could read any event's scoreboard
    just by knowing the event UUID. The fix is event-scoped: organizers must own,
    participants must be registered for the requested event.
    """

    def test_denies_other_organizer(
        self,
        rf,
        mock_non_owner_user,
        _patch_get_event,
        _patch_role_organizer,
        _patch_participant_membership_false,
    ):
        """A CTF organizer who does not own this event AND is not registered
        for it as a participant gets 403 — possession of an organizer role
        on the platform is not access to an arbitrary event's scoreboard.
        """
        from ctf.views import api_scoreboard

        request = _get_request(rf, mock_non_owner_user)
        response = api_scoreboard(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_denies_unrelated_participant(
        self,
        rf,
        mock_participant_user,
        _patch_get_event,
        _patch_role_participant,
        _patch_participant_membership_false,
    ):
        from ctf.views import api_scoreboard

        request = _get_request(rf, mock_participant_user)
        response = api_scoreboard(request, event_id=EVENT_ID)
        assert response.status_code == 403

    def test_allows_owner_organizer(
        self,
        rf,
        mock_owner_user,
        _patch_get_event,
        _patch_role_organizer,
        _patch_no_brackets,
        _patch_empty_scoreboard,
    ):
        from ctf.views import api_scoreboard

        request = _get_request(rf, mock_owner_user)
        response = api_scoreboard(request, event_id=EVENT_ID)
        assert response.status_code == 200

    def test_allows_assigned_participant(
        self,
        rf,
        mock_participant_user,
        _patch_get_event,
        _patch_role_participant,
        _patch_participant_membership_true,
        _patch_no_brackets,
        _patch_empty_scoreboard,
    ):
        from ctf.views import api_scoreboard

        request = _get_request(rf, mock_participant_user)
        response = api_scoreboard(request, event_id=EVENT_ID)
        assert response.status_code == 200

    def test_returns_404_when_event_missing_before_403(self, rf, mock_non_owner_user, _patch_role_organizer):
        """Probing UUIDs must not get a different shape after the fix.

        404 must come BEFORE the new 403 check so a stranger probing event UUIDs
        can't tell "exists but not yours" from "does not exist."
        """
        from ctf.exceptions import CTFNotFoundError
        from ctf.views import api_scoreboard

        with patch("ctf.services.get_event", side_effect=CTFNotFoundError("no")):
            request = _get_request(rf, mock_non_owner_user)
            response = api_scoreboard(request, event_id=EVENT_ID)
        assert response.status_code == 404


# ===========================================================================
# Issue #769 — api_use_hint route/body challenge-id coherence
# ===========================================================================


class TestAPIUseHint:
    """API-layer wiring tests for the hint unlock endpoint.

    Coherence enforcement (URL `challenge_id` ↔ hint.challenge_id) lives in
    the hint service via `use_hint(..., expected_challenge_id=...)`; the
    actual rejection is exercised in
    `tests/ctf/test_services/test_hint.py::TestHintExpectedChallenge`.
    Here we verify the *wiring*: the view always forwards the URL
    challenge_id to the service, and malformed body input gets a 400.
    """

    def test_api_use_hint_passes_url_challenge_id_to_service(self, rf):
        """The view MUST forward the URL `challenge_id` as
        `expected_challenge_id` so the service-side coherence check fires.

        If this wiring breaks, a hint_id pointing at a different challenge
        in the same event would unlock without rejection.
        """
        from ctf.views import api_use_hint
        from shared.auth import CTF_PARTICIPANT_GROUP

        url_challenge_id = uuid.uuid4()
        body_hint_id = uuid.uuid4()

        user = _make_mock_user(pk=99, email="participant@test.com", groups={CTF_PARTICIPANT_GROUP})
        mock_participant = MagicMock()
        mock_participant.id = uuid.uuid4()
        mock_participant.user = user

        # Cycle 4 added a `get_challenge` lookup before participant
        # resolution (so participants resolve scoped to the route's event);
        # mock that and the participant resolver. `use_hint` is imported
        # lazily inside `api_use_hint`, so patch at source
        # (`ctf.services.hint.use_hint`).
        mock_challenge = MagicMock(id=url_challenge_id, event_id=uuid.uuid4())
        with (
            patch("ctf.services.participant.is_active_participant", return_value=True),
            patch("ctf.services.challenge.get_challenge", return_value=mock_challenge),
            patch("ctf.views._get_participant_for_challenge", return_value=mock_participant),
            patch("ctf.services.hint.use_hint") as mock_use_hint,
        ):
            mock_use_hint.return_value = {
                "text": "x",
                "penalty": 0,
                "order": 0,
                "total_penalty": 0,
                "already_unlocked": False,
            }

            request = _get_request(
                rf,
                user,
                method="post",
                data=f'{{"hint_id": "{body_hint_id}"}}',
                content_type="application/json",
            )
            api_use_hint(request, challenge_id=url_challenge_id)

        mock_use_hint.assert_called_once()
        _args, kwargs = mock_use_hint.call_args
        assert kwargs["expected_challenge_id"] == url_challenge_id

    def test_api_use_hint_returns_400_for_malformed_body_uuid(self, rf):
        """A non-UUID `hint_id` in the body must produce a 400 with the
        standard JSON error envelope, never a 500. Closes the codex review
        finding (issue #769) about request-body UUID conversion leaking
        ValueError out of the view.
        """
        from ctf.views import api_use_hint
        from shared.auth import CTF_PARTICIPANT_GROUP

        url_challenge_id = uuid.uuid4()
        user = _make_mock_user(pk=99, email="participant@test.com", groups={CTF_PARTICIPANT_GROUP})
        mock_participant = MagicMock()
        mock_participant.id = uuid.uuid4()
        mock_participant.user = user

        mock_challenge = MagicMock(id=url_challenge_id, event_id=uuid.uuid4())
        with (
            patch("ctf.services.participant.is_active_participant", return_value=True),
            patch("ctf.services.challenge.get_challenge", return_value=mock_challenge),
            patch("ctf.views._get_participant_for_challenge", return_value=mock_participant),
        ):
            request = _get_request(
                rf,
                user,
                method="post",
                data='{"hint_id": "not-a-uuid"}',
                content_type="application/json",
            )
            response = api_use_hint(request, challenge_id=url_challenge_id)

        assert response.status_code == 400, response.content
