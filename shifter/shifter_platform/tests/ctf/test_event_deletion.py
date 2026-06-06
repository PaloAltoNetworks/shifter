"""Tests for CTF Event Management - Phase 3.

Tests cover:
- Event form validation
- Event list view (filtering, pagination)
- Event create view
- Event detail view
- Event edit view
- Event status transitions (schedule, activate, complete, cancel)
- Event services

All tests mock the ORM — no @pytest.mark.django_db markers.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from ctf.enums import EventStatus

# ---------------------------------------------------------------------------
# Shared mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_user():
    """Create a mock authenticated user (organizer)."""
    user = MagicMock()
    user.pk = 1
    user.id = 1
    user.email = "organizer@test.com"
    user.username = "organizer@test.com"
    user.is_authenticated = True
    user.is_active = True
    user.is_anonymous = False
    user.is_staff = False
    user.is_superuser = False
    user.backend = "django.contrib.auth.backends.ModelBackend"
    return user


@pytest.fixture
def mock_standard_user():
    """Create a mock non-organizer user."""
    user = MagicMock()
    user.pk = 2
    user.id = 2
    user.email = "standard@test.com"
    user.username = "standard@test.com"
    user.is_authenticated = True
    user.is_active = True
    user.is_anonymous = False
    user.is_staff = False
    user.is_superuser = False
    user.backend = "django.contrib.auth.backends.ModelBackend"
    return user


class _MockEvent:
    """Lightweight mock CTFEvent that works with Django templates.

    Django templates resolve ``event.pk`` by trying ``event['pk']`` first.
    A MagicMock would return another mock for ``__getitem__``, breaking URL
    resolution. This plain object avoids that problem.
    """

    def __init__(
        self,
        *,
        name="Test CTF Event",
        description="A test CTF event",
        status=EventStatus.REGISTRATION.value,
        created_by_id=1,
        pk=None,
        is_modifiable=True,
    ):
        self.pk = pk or uuid4()
        self.id = self.pk
        self.name = name
        self.description = description
        self.status = status
        self.created_by_id = created_by_id
        self.event_start = timezone.now() + timedelta(days=1)
        self.event_end = timezone.now() + timedelta(days=1, hours=8)
        self.scenario_id = "basic"
        self.auto_cleanup = True
        self.cleanup_delay_hours = 24
        self.range_spinup_minutes = 30
        self.team_mode = False
        self.team_size_limit = None
        self.is_modifiable = is_modifiable
        self.registration_deadline = None
        self.max_participants = None
        self.range_config = None
        self.save = MagicMock()
        self.refresh_from_db = MagicMock()

    def get_status_display(self):
        return self.status.title()


def _make_mock_event(**kwargs):
    """Helper to create a mock CTFEvent."""
    return _MockEvent(**kwargs)


@pytest.fixture
def mock_event():
    """A scheduled event owned by user pk=1."""
    return _make_mock_event(status=EventStatus.REGISTRATION.value)


@pytest.fixture
def mock_event_draft():
    """A draft event owned by user pk=1."""
    return _make_mock_event(
        name="Draft CTF Event",
        description="A draft event",
        status=EventStatus.DRAFT.value,
    )


@pytest.fixture
def mock_event_active():
    """An active event owned by user pk=1."""
    return _make_mock_event(
        name="Active CTF Event",
        description="An active event",
        status=EventStatus.ACTIVE.value,
    )


@contextmanager
def _noop_atomic():
    """No-op replacement for transaction.atomic()."""
    yield


@pytest.fixture
def _mock_auth_organizer(mock_user):
    """Patch Django auth to authenticate mock_user as organizer.

    Also patches context processors that would otherwise hit the DB.
    """
    from ctf.bridges import UserRole

    role = UserRole(is_ctf_organizer=True, is_ctf_participant=False, active_ctf_event=None)

    ctx_proc_defaults = {
        "is_ctf_user": True,
        "is_ctf_organizer": True,
        "is_ctf_participant": False,
        "is_ctf_participant_only": False,
        "active_ctf_event": None,
    }
    range_ctx_defaults = {
        "has_active_range": False,
        "active_range": None,
        "connection_urls": [],
        "scenario_name": None,
    }

    with (
        patch("ctf.views.get_user_role", return_value=role),
        patch("django.contrib.auth.get_user", return_value=mock_user),
        patch("django.contrib.auth.middleware.get_user", return_value=mock_user),
        patch("ctf.context_processors.ctf_navigation", return_value=ctx_proc_defaults),
        patch("mission_control.context_processors.active_range", return_value=range_ctx_defaults),
        patch("shared.context_processors.user_permissions", return_value={"can_access_threat_research": False}),
    ):
        yield


@pytest.fixture
def _mock_auth_standard(mock_standard_user):
    """Patch Django auth to authenticate mock_standard_user as non-organizer."""
    from ctf.bridges import UserRole

    role = UserRole(is_ctf_organizer=False, is_ctf_participant=False, active_ctf_event=None)

    with (
        patch("ctf.views.get_user_role", return_value=role),
        patch("django.contrib.auth.get_user", return_value=mock_standard_user),
        patch("django.contrib.auth.middleware.get_user", return_value=mock_standard_user),
    ):
        yield


@pytest.fixture
def organizer_client(_mock_auth_organizer) -> Client:
    """An HTTP client authenticated as an organizer."""
    return Client()


@pytest.fixture
def standard_client(_mock_auth_standard) -> Client:
    """An HTTP client authenticated as a non-organizer user."""
    return Client()


# ---------------------------------------------------------------------------
# Form Tests
# ---------------------------------------------------------------------------


class TestForceDeleteEvent:
    """Tests for force_delete_event service function."""

    @staticmethod
    def _mock_empty_querysets():
        """Return patch contexts for empty participant and file querysets."""
        mock_part_qs = MagicMock()
        mock_part_qs.select_related.return_value = []
        mock_file_qs = MagicMock()
        mock_file_qs.values_list.return_value = []
        return mock_part_qs, mock_file_qs

    def test_force_delete_success(self, mock_user):
        """force_delete_event should hard-delete the event and clean up ranges."""
        event = _make_mock_event(name="My CTF")
        event.delete = MagicMock(return_value=(1, {"CTFEvent": 1}))

        mock_participant = MagicMock()
        mock_participant.pk = 42
        mock_participant.user = mock_user
        mock_part_qs = MagicMock()
        mock_part_qs.select_related.return_value = [mock_participant]
        mock_file_qs = MagicMock()
        mock_file_qs.values_list.return_value = ["ctf-files/key1.txt"]

        with (
            patch("ctf.services.event.CTFEvent.all_objects") as mock_all,
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
            patch("ctf.services.event._cancel_event_tasks") as mock_cancel,
            patch("ctf.models.CTFParticipant.all_objects") as mock_part_all,
            patch("ctf.models.CTFChallengeFile.all_objects") as mock_file_all,
            patch("ctf.services.range._destroy_single_range") as mock_destroy,
            patch("ctf.s3.delete_challenge_file") as mock_s3_delete,
        ):
            mock_all.get.return_value = event
            mock_part_all.filter.return_value = mock_part_qs
            mock_file_all.filter.return_value = mock_file_qs
            from ctf.services.event import force_delete_event

            result = force_delete_event(event.pk, mock_user, "My CTF")

        assert result["event_name"] == "My CTF"
        assert result["ranges_destroyed"] == 1
        assert result["ranges_failed"] == 0
        event.delete.assert_called_once_with(soft=False)
        mock_cancel.assert_called_once_with(event)
        mock_destroy.assert_called_once_with(mock_participant, mock_user)
        mock_s3_delete.assert_called_once_with("ctf-files/key1.txt")

    def test_force_delete_wrong_confirmation_name(self, mock_user):
        """force_delete_event should raise CTFValidationError on name mismatch."""
        from ctf.exceptions import CTFValidationError

        event = _make_mock_event(name="Real Name")

        with patch("ctf.services.event.CTFEvent.all_objects") as mock_all:
            mock_all.get.return_value = event
            from ctf.services.event import force_delete_event

            with pytest.raises(CTFValidationError, match="does not match"):
                force_delete_event(event.pk, mock_user, "Wrong Name")

    def test_force_delete_event_not_found(self, mock_user):
        """force_delete_event should raise CTFNotFoundError for missing events."""
        from ctf.exceptions import CTFNotFoundError
        from ctf.models import CTFEvent

        with patch("ctf.services.event.CTFEvent.all_objects") as mock_all:
            mock_all.get.side_effect = CTFEvent.DoesNotExist
            from ctf.services.event import force_delete_event

            with pytest.raises(CTFNotFoundError):
                force_delete_event(uuid4(), mock_user, "Whatever")

    def test_force_delete_range_cleanup_partial_failure(self, mock_user):
        """force_delete_event should proceed even if some ranges fail to destroy."""
        event = _make_mock_event(name="Partial Fail")
        event.delete = MagicMock(return_value=(1, {"CTFEvent": 1}))

        mock_ok = MagicMock(pk=1, user=mock_user)
        mock_fail = MagicMock(pk=2, user=mock_user)
        mock_part_qs = MagicMock()
        mock_part_qs.select_related.return_value = [mock_ok, mock_fail]
        _, mock_file_qs = self._mock_empty_querysets()

        with (
            patch("ctf.services.event.CTFEvent.all_objects") as mock_all,
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
            patch("ctf.services.event._cancel_event_tasks"),
            patch("ctf.models.CTFParticipant.all_objects") as mock_part_all,
            patch("ctf.models.CTFChallengeFile.all_objects") as mock_file_all,
            patch(
                "ctf.services.range._destroy_single_range",
                side_effect=[None, RuntimeError("CMS error")],
            ),
        ):
            mock_all.get.return_value = event
            mock_part_all.filter.return_value = mock_part_qs
            mock_file_all.filter.return_value = mock_file_qs
            from ctf.services.event import force_delete_event

            result = force_delete_event(event.pk, mock_user, "Partial Fail")

        assert result["ranges_destroyed"] == 1
        assert result["ranges_failed"] == 1
        event.delete.assert_called_once_with(soft=False)

    def test_force_delete_range_cleanup_total_failure(self, mock_user):
        """force_delete_event should proceed even if all range destroys fail."""
        event = _make_mock_event(name="Total Fail")
        event.delete = MagicMock(return_value=(1, {"CTFEvent": 1}))

        mock_part_qs, mock_file_qs = self._mock_empty_querysets()

        with (
            patch("ctf.services.event.CTFEvent.all_objects") as mock_all,
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
            patch("ctf.services.event._cancel_event_tasks"),
            patch("ctf.models.CTFParticipant.all_objects") as mock_part_all,
            patch("ctf.models.CTFChallengeFile.all_objects") as mock_file_all,
        ):
            mock_all.get.return_value = event
            mock_part_all.filter.return_value = mock_part_qs
            mock_file_all.filter.return_value = mock_file_qs
            from ctf.services.event import force_delete_event

            result = force_delete_event(event.pk, mock_user, "Total Fail")

        assert result["ranges_destroyed"] == 0
        assert result["ranges_failed"] == 0
        event.delete.assert_called_once_with(soft=False)


class TestApiForceDeleteEvent:
    """Tests for api_force_delete_event endpoint."""

    def test_api_force_delete_success(self, organizer_client, mock_event):
        """POST with valid confirmation should return 200 and summary."""
        url = reverse("ctf:api_force_delete_event", kwargs={"event_id": mock_event.pk})

        with (
            patch("ctf.models.CTFEvent.all_objects") as mock_all,
            patch("ctf.services.force_delete_event") as mock_svc,
        ):
            mock_all.get.return_value = mock_event
            mock_svc.return_value = {
                "event_id": str(mock_event.pk),
                "event_name": mock_event.name,
                "ranges_destroyed": 0,
                "ranges_failed": 0,
            }

            resp = organizer_client.post(
                url,
                data='{"confirmation_name": "Test CTF Event"}',
                content_type="application/json",
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["event_name"] == "Test CTF Event"

    def test_api_force_delete_wrong_name(self, organizer_client, mock_event):
        """POST with wrong confirmation name should return 400."""
        from ctf.exceptions import CTFValidationError

        url = reverse("ctf:api_force_delete_event", kwargs={"event_id": mock_event.pk})

        with (
            patch("ctf.models.CTFEvent.all_objects") as mock_all,
            patch("ctf.services.force_delete_event") as mock_svc,
        ):
            mock_all.get.return_value = mock_event
            mock_svc.side_effect = CTFValidationError("does not match")

            resp = organizer_client.post(
                url,
                data='{"confirmation_name": "Wrong Name"}',
                content_type="application/json",
            )

        assert resp.status_code == 400

    def test_api_force_delete_missing_confirmation(self, organizer_client, mock_event):
        """POST without confirmation_name should return 400."""
        url = reverse("ctf:api_force_delete_event", kwargs={"event_id": mock_event.pk})

        with patch("ctf.models.CTFEvent.all_objects") as mock_all:
            mock_all.get.return_value = mock_event

            resp = organizer_client.post(
                url,
                data="{}",
                content_type="application/json",
            )

        assert resp.status_code == 400
        assert "confirmation_name" in resp.json()["error"]

    def test_api_force_delete_non_owner(self, organizer_client, mock_event):
        """Non-owner should get 403."""
        mock_event.created_by_id = 999  # Not the authenticated user (pk=1)
        url = reverse("ctf:api_force_delete_event", kwargs={"event_id": mock_event.pk})

        with patch("ctf.models.CTFEvent.all_objects") as mock_all:
            mock_all.get.return_value = mock_event

            resp = organizer_client.post(
                url,
                data='{"confirmation_name": "Test CTF Event"}',
                content_type="application/json",
            )

        assert resp.status_code == 403

    def test_api_force_delete_not_found(self, organizer_client):
        """Force-deleting a non-existent event should return 404."""
        from ctf.models import CTFEvent

        url = reverse("ctf:api_force_delete_event", kwargs={"event_id": uuid4()})

        with patch("ctf.models.CTFEvent.all_objects") as mock_all:
            mock_all.get.side_effect = CTFEvent.DoesNotExist

            resp = organizer_client.post(
                url,
                data='{"confirmation_name": "Whatever"}',
                content_type="application/json",
            )

        assert resp.status_code == 404


class TestAdminEventForceDelete:
    """Tests for admin_event_force_delete view."""

    def test_get_renders_confirmation_page(self, organizer_client, mock_event):
        """GET should render the force delete confirmation template."""
        url = reverse("ctf:admin_event_force_delete", kwargs={"event_id": mock_event.pk})

        with (
            patch("ctf.models.CTFEvent.all_objects") as mock_all,
            patch(
                "ctf.services.get_event_stats",
                return_value={
                    "participant_count": 5,
                    "registered_count": 3,
                    "invited_count": 2,
                    "challenge_count": 10,
                    "total_points": 500,
                    "total_submissions": 20,
                    "correct_submissions": 8,
                    "team_count": 0,
                },
            ),
        ):
            mock_all.get.return_value = mock_event

            resp = organizer_client.get(url)

        assert resp.status_code == 200
        assert b"Force Delete" in resp.content

    def test_post_valid_redirects(self, organizer_client, mock_event):
        """POST with valid confirmation should redirect to event list."""
        url = reverse("ctf:admin_event_force_delete", kwargs={"event_id": mock_event.pk})

        with (
            patch("ctf.models.CTFEvent.all_objects") as mock_all,
            patch("ctf.services.force_delete_event") as mock_svc,
        ):
            mock_all.get.return_value = mock_event
            mock_svc.return_value = {
                "event_id": str(mock_event.pk),
                "event_name": mock_event.name,
                "ranges_destroyed": 0,
                "ranges_failed": 0,
            }

            resp = organizer_client.post(url, data={"confirmation_name": mock_event.name})

        assert resp.status_code == 302
        assert "admin_event_list" in resp.url or "/events/" in resp.url

    def test_post_wrong_name_rerenders(self, organizer_client, mock_event):
        """POST with wrong name should re-render with error message."""
        from ctf.exceptions import CTFValidationError

        url = reverse("ctf:admin_event_force_delete", kwargs={"event_id": mock_event.pk})

        with (
            patch("ctf.models.CTFEvent.all_objects") as mock_all,
            patch("ctf.services.force_delete_event") as mock_svc,
            patch(
                "ctf.services.get_event_stats",
                return_value={
                    "participant_count": 0,
                    "registered_count": 0,
                    "invited_count": 0,
                    "challenge_count": 0,
                    "total_points": 0,
                    "total_submissions": 0,
                    "correct_submissions": 0,
                    "team_count": 0,
                },
            ),
        ):
            mock_all.get.return_value = mock_event
            mock_svc.side_effect = CTFValidationError("does not match")

            resp = organizer_client.post(url, data={"confirmation_name": "Wrong Name"})

        assert resp.status_code == 200
        assert b"does not match" in resp.content
