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


class TestCTFEventForm:
    """Test CTFEventForm validation.

    Form tests do not need DB access — CTFEventForm with user=None uses
    a plain CharField for scenario_id, so no ORM calls occur.
    """

    def test_form_valid_minimal_data(self):
        """Form should accept minimal valid data."""
        from ctf.forms import CTFEventForm

        data = {
            "name": "Test Event",
            "description": "A test event",
            "event_start": timezone.now() + timedelta(days=1),
            "event_end": timezone.now() + timedelta(days=1, hours=8),
            "scenario_id": "basic",
            "auto_cleanup": True,
            "cleanup_delay_hours": 24,
            "range_spinup_minutes": 30,
            "team_mode": False,
            "submission_cooldown_seconds": 0,
            "attempt_limit_mode": "lockout",
            "attempt_limit_cooldown_seconds": 300,
            "rating_visibility": "public",
        }
        form = CTFEventForm(data=data)
        assert form.is_valid(), form.errors

    def test_form_valid_team_mode(self):
        """Form should accept team mode with size limit."""
        from ctf.forms import CTFEventForm

        data = {
            "name": "Team Event",
            "description": "A team event",
            "event_start": timezone.now() + timedelta(days=1),
            "event_end": timezone.now() + timedelta(days=1, hours=8),
            "scenario_id": "basic",
            "auto_cleanup": True,
            "cleanup_delay_hours": 24,
            "range_spinup_minutes": 30,
            "team_mode": True,
            "team_size_limit": 4,
            "submission_cooldown_seconds": 0,
            "attempt_limit_mode": "lockout",
            "attempt_limit_cooldown_seconds": 300,
            "rating_visibility": "public",
        }
        form = CTFEventForm(data=data)
        assert form.is_valid(), form.errors

    def test_form_invalid_end_before_start(self):
        """Form should reject end time before start time."""
        from ctf.forms import CTFEventForm

        start = timezone.now() + timedelta(days=1, hours=8)
        end = timezone.now() + timedelta(days=1)  # Before start
        data = {
            "name": "Invalid Event",
            "description": "Invalid times",
            "event_start": start.strftime("%Y-%m-%dT%H:%M"),
            "event_end": end.strftime("%Y-%m-%dT%H:%M"),
            "scenario_id": "basic",
            "auto_cleanup": True,
            "cleanup_delay_hours": 24,
            "range_spinup_minutes": 30,
            "team_mode": False,
        }
        form = CTFEventForm(data=data)
        assert not form.is_valid()
        assert "event_end" in form.errors

    def test_form_invalid_team_mode_without_size(self):
        """Form should reject team mode without size limit."""
        from ctf.forms import CTFEventForm

        data = {
            "name": "Team Event",
            "description": "Missing team size",
            "event_start": timezone.now() + timedelta(days=1),
            "event_end": timezone.now() + timedelta(days=1, hours=8),
            "scenario_id": "basic",
            "auto_cleanup": True,
            "cleanup_delay_hours": 24,
            "range_spinup_minutes": 30,
            "team_mode": True,
            # Missing team_size_limit
        }
        form = CTFEventForm(data=data)
        assert not form.is_valid()
        assert "team_size_limit" in form.errors

    def test_form_invalid_registration_deadline_after_start(self):
        """Form should reject registration deadline after event start."""
        from ctf.forms import CTFEventForm

        start = timezone.now() + timedelta(days=1)
        data = {
            "name": "Invalid Deadline Event",
            "description": "Registration after start",
            "event_start": start,
            "event_end": start + timedelta(hours=8),
            "registration_deadline": start + timedelta(hours=1),  # After start
            "scenario_id": "basic",
            "auto_cleanup": True,
            "cleanup_delay_hours": 24,
            "range_spinup_minutes": 30,
            "team_mode": False,
        }
        form = CTFEventForm(data=data)
        assert not form.is_valid()
        assert "registration_deadline" in form.errors

    def test_form_with_optional_fields(self):
        """Form should accept all optional fields."""
        from ctf.forms import CTFEventForm

        start = timezone.now() + timedelta(days=7)
        data = {
            "name": "Full Event",
            "description": "With all optional fields",
            "event_start": start,
            "event_end": start + timedelta(hours=12),
            "registration_deadline": start - timedelta(days=1),
            "scenario_id": "advanced",
            "auto_cleanup": True,
            "cleanup_delay_hours": 48,
            "range_spinup_minutes": 60,
            "max_participants": 50,
            "team_mode": True,
            "team_size_limit": 5,
            "submission_cooldown_seconds": 10,
            "attempt_limit_mode": "timeout",
            "attempt_limit_cooldown_seconds": 600,
            "rating_visibility": "organizer",
        }
        form = CTFEventForm(data=data)
        assert form.is_valid(), form.errors


# ---------------------------------------------------------------------------
# Event List View Tests
# ---------------------------------------------------------------------------


class TestEventListView:
    """Test event list view for organizers."""

    def test_event_list_requires_login(self):
        """Event list should require authentication."""
        client = Client()
        response = client.get(reverse("ctf:admin_event_list"))
        assert response.status_code == 302  # Redirect to login

    def test_event_list_requires_organizer(self, standard_client: Client):
        """Event list should require organizer role."""
        response = standard_client.get(reverse("ctf:admin_event_list"))
        assert response.status_code == 403

    def test_event_list_shows_organizer_events(self, organizer_client: Client, mock_event):
        """Organizer should see their own events."""
        with patch("ctf.services.get_organizer_events", return_value=[mock_event]):
            response = organizer_client.get(reverse("ctf:admin_event_list"))
        assert response.status_code == 200
        assert mock_event.name in response.content.decode()

    def test_event_list_filter_by_status(self, organizer_client: Client, mock_event, mock_event_draft):
        """Event list should filter by status."""
        with patch("ctf.services.get_organizer_events", return_value=[mock_event_draft]):
            response = organizer_client.get(reverse("ctf:admin_event_list") + "?status=draft")
        assert response.status_code == 200
        content = response.content.decode()
        assert mock_event_draft.name in content
        assert mock_event.name not in content

    def test_event_list_shows_all_statuses_by_default(self, organizer_client: Client, mock_event, mock_event_draft):
        """Event list should show all events by default."""
        with patch("ctf.services.get_organizer_events", return_value=[mock_event, mock_event_draft]):
            response = organizer_client.get(reverse("ctf:admin_event_list"))
        assert response.status_code == 200
        content = response.content.decode()
        assert mock_event.name in content
        assert mock_event_draft.name in content

    def test_event_list_hides_other_organizer_events(self, organizer_client: Client):
        """Organizer should not see other organizers' events."""
        other_event = _make_mock_event(
            name="Other Organizer Event",
            created_by_id=3,
        )
        # get_organizer_events filters by user, so return empty for the logged-in organizer
        with patch("ctf.services.get_organizer_events", return_value=[]):
            response = organizer_client.get(reverse("ctf:admin_event_list"))
        assert response.status_code == 200
        assert other_event.name not in response.content.decode()


# ---------------------------------------------------------------------------
# Event Create View Tests
# ---------------------------------------------------------------------------


class TestEventCreateView:
    """Test event creation view."""

    def test_create_view_requires_login(self):
        """Create view should require authentication."""
        client = Client()
        response = client.get(reverse("ctf:admin_event_create"))
        assert response.status_code == 302

    def test_create_view_requires_organizer(self, standard_client: Client):
        """Create view should require organizer role."""
        response = standard_client.get(reverse("ctf:admin_event_create"))
        assert response.status_code == 403

    def test_create_view_renders_form(self, organizer_client: Client):
        """Create view should render the AJAX form template with scenarios."""
        with patch("ctf.bridges.cms_list_scenarios", return_value=[("basic", "Basic")]):
            response = organizer_client.get(reverse("ctf:admin_event_create"))
        assert response.status_code == 200
        assert "scenarios_json" in response.context

    def test_create_view_is_get_only(self, organizer_client: Client):
        """Create view should reject POST (form submission is via API now)."""
        response = organizer_client.post(reverse("ctf:admin_event_create"), data={})
        assert response.status_code == 405


# ---------------------------------------------------------------------------
# Event Detail View Tests
# ---------------------------------------------------------------------------


class TestEventDetailView:
    """Test event detail view."""

    def _patch_detail_deps(self, event):
        """Return tuple of patch context managers for detail view dependencies."""
        stats = {
            "participant_count": 1,
            "registered_count": 1,
            "invited_count": 0,
            "challenge_count": 1,
            "team_count": 0,
            "total_submissions": 0,
            "correct_submissions": 0,
            "total_points": 100,
        }
        return (
            patch("ctf.services.get_event", return_value=event),
            patch("ctf.services.get_event_stats", return_value=stats),
        )

    def test_detail_view_requires_login(self, mock_event):
        """Detail view should require authentication."""
        client = Client()
        response = client.get(reverse("ctf:admin_event_detail", kwargs={"event_id": mock_event.pk}))
        assert response.status_code == 302

    def test_detail_view_requires_organizer(self, standard_client: Client, mock_event):
        """Detail view should require organizer role."""
        response = standard_client.get(reverse("ctf:admin_event_detail", kwargs={"event_id": mock_event.pk}))
        assert response.status_code == 403

    def test_detail_view_shows_event(self, organizer_client: Client, mock_event):
        """Detail view should show event information."""
        p1, p2 = self._patch_detail_deps(mock_event)
        with p1, p2:
            response = organizer_client.get(reverse("ctf:admin_event_detail", kwargs={"event_id": mock_event.pk}))
        assert response.status_code == 200
        assert mock_event.name in response.content.decode()

    def test_detail_view_shows_stats(self, organizer_client: Client, mock_event):
        """Detail view should show event statistics."""
        p1, p2 = self._patch_detail_deps(mock_event)
        with p1, p2:
            response = organizer_client.get(reverse("ctf:admin_event_detail", kwargs={"event_id": mock_event.pk}))
        assert response.status_code == 200
        assert "event" in response.context

    def test_detail_view_404_for_nonexistent(self, organizer_client: Client):
        """Detail view should 404 for nonexistent event."""
        from ctf.exceptions import CTFNotFoundError

        with patch("ctf.services.get_event", side_effect=CTFNotFoundError("not found")):
            response = organizer_client.get(reverse("ctf:admin_event_detail", kwargs={"event_id": uuid4()}))
        assert response.status_code == 404

    def test_detail_view_403_for_other_organizer_event(self, organizer_client: Client):
        """Organizer should not access other organizer's event."""
        other_event = _make_mock_event(
            name="Other Event",
            created_by_id=999,  # Not our organizer (pk=1)
        )
        stats = {
            "participant_count": 0,
            "registered_count": 0,
            "invited_count": 0,
            "challenge_count": 0,
            "team_count": 0,
            "total_submissions": 0,
            "correct_submissions": 0,
            "total_points": 0,
        }
        with (
            patch("ctf.services.get_event", return_value=other_event),
            patch("ctf.services.get_event_stats", return_value=stats),
        ):
            response = organizer_client.get(reverse("ctf:admin_event_detail", kwargs={"event_id": other_event.pk}))
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Event Edit View Tests
# ---------------------------------------------------------------------------


class TestEventEditView:
    """Test event edit view."""

    def test_edit_view_requires_login(self, mock_event):
        """Edit view should require authentication."""
        client = Client()
        response = client.get(reverse("ctf:admin_event_edit", kwargs={"event_id": mock_event.pk}))
        assert response.status_code == 302

    def test_edit_view_requires_organizer(self, standard_client: Client, mock_event):
        """Edit view should require organizer role."""
        response = standard_client.get(reverse("ctf:admin_event_edit", kwargs={"event_id": mock_event.pk}))
        assert response.status_code == 403

    def test_edit_view_renders_form_with_data(self, organizer_client: Client, mock_event_draft):
        """Edit view should render AJAX form template with scenarios and event_id."""
        with (
            patch("ctf.services.get_event", return_value=mock_event_draft),
            patch("ctf.bridges.cms_list_scenarios", return_value=[("basic", "Basic")]),
        ):
            response = organizer_client.get(reverse("ctf:admin_event_edit", kwargs={"event_id": mock_event_draft.pk}))
        assert response.status_code == 200
        assert "scenarios_json" in response.context
        assert response.context["is_edit"] is True
        assert response.context["event_id"] == str(mock_event_draft.pk)

    def test_edit_view_is_get_only(self, organizer_client: Client, mock_event_draft):
        """Edit view should reject POST (form submission is via API now)."""
        response = organizer_client.post(
            reverse("ctf:admin_event_edit", kwargs={"event_id": mock_event_draft.pk}),
            data={},
        )
        assert response.status_code == 405

    def test_edit_completed_event_blocked(self, organizer_client: Client):
        """Editing a completed event should be blocked."""
        completed_event = _make_mock_event(
            name="Completed Event",
            status=EventStatus.ENDED.value,
            is_modifiable=False,
        )
        with (
            patch("ctf.services.get_event", return_value=completed_event),
            patch("ctf.bridges.cms_list_scenarios", return_value=[("basic", "Basic")]),
        ):
            response = organizer_client.get(reverse("ctf:admin_event_edit", kwargs={"event_id": completed_event.pk}))
        # Should redirect or show error
        assert response.status_code in (302, 403)


# ---------------------------------------------------------------------------
# Event Status Transition Tests
# ---------------------------------------------------------------------------


class TestEventStatusTransitions:
    """Test event status transitions via service functions.

    These test the pure business logic: status guards and field mutation.
    ORM .save() and .refresh_from_db() are mocked on the event objects.
    """

    def test_schedule_draft_event(self, mock_event_draft):
        """Should be able to schedule a draft event."""
        with patch("ctf.services.event._schedule_event_tasks"):
            from ctf.services import schedule_event

            result = schedule_event(mock_event_draft)
        assert result is True
        assert mock_event_draft.status == EventStatus.REGISTRATION.value
        mock_event_draft.save.assert_called_once()

    def test_activate_scheduled_event(self, mock_event):
        """Should be able to activate a scheduled event."""
        from ctf.services import activate_event

        result = activate_event(mock_event)
        assert result is True
        assert mock_event.status == EventStatus.ACTIVE.value
        mock_event.save.assert_called_once()

    def test_complete_active_event(self, mock_event_active):
        """Should be able to complete an active event."""
        from ctf.services import complete_event

        with patch("ctf.services.range.cleanup_event_ranges"):
            result = complete_event(mock_event_active)
        assert result is True
        assert mock_event_active.status == EventStatus.ENDED.value
        mock_event_active.save.assert_called_once()

    def test_cancel_draft_event(self, mock_event_draft):
        """Should be able to cancel a draft event."""
        with (
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
            patch("ctf.services.event._cancel_event_tasks"),
            patch("ctf.services.range.cleanup_event_ranges"),
        ):
            from ctf.services import cancel_event

            result = cancel_event(mock_event_draft)
        assert result is True
        assert mock_event_draft.status == EventStatus.CANCELLED.value

    def test_cancel_scheduled_event(self, mock_event):
        """Should be able to cancel a scheduled event."""
        with (
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
            patch("ctf.services.event._cancel_event_tasks"),
            patch("ctf.services.range.cleanup_event_ranges"),
        ):
            from ctf.services import cancel_event

            result = cancel_event(mock_event)
        assert result is True
        assert mock_event.status == EventStatus.CANCELLED.value

    def test_cannot_activate_draft_event(self, mock_event_draft):
        """Should not be able to activate a draft event directly."""
        from ctf.services import activate_event

        result = activate_event(mock_event_draft)
        assert result is False
        # Status should remain draft
        assert mock_event_draft.status == EventStatus.DRAFT.value

    def test_cannot_schedule_active_event(self, mock_event_active):
        """Should not be able to schedule an active event."""
        from ctf.services import schedule_event

        result = schedule_event(mock_event_active)
        assert result is False

    def test_cannot_modify_ended_event(self):
        """Ended events should not be modifiable."""
        ended_event = _make_mock_event(
            name="Ended",
            status=EventStatus.ENDED.value,
            is_modifiable=False,
        )
        assert ended_event.is_modifiable is False

    def test_pause_active_event(self, mock_event_active):
        """Should be able to pause an active event."""
        from ctf.services import pause_event

        result = pause_event(mock_event_active)
        assert result is True
        assert mock_event_active.status == EventStatus.PAUSED.value
        mock_event_active.save.assert_called_once()

    def test_resume_paused_event(self):
        """Should be able to resume a paused event."""
        from ctf.services import resume_event

        paused_event = _make_mock_event(status=EventStatus.PAUSED.value)
        result = resume_event(paused_event)
        assert result is True
        assert paused_event.status == EventStatus.ACTIVE.value

    def test_archive_ended_event(self):
        """Should be able to archive an ended event."""
        from ctf.services import archive_event

        ended_event = _make_mock_event(status=EventStatus.ENDED.value)
        result = archive_event(ended_event)
        assert result is True
        assert ended_event.status == EventStatus.ARCHIVED.value

    def test_cannot_pause_draft_event(self, mock_event_draft):
        """Should not be able to pause a draft event."""
        from ctf.services import pause_event

        result = pause_event(mock_event_draft)
        assert result is False
        assert mock_event_draft.status == EventStatus.DRAFT.value

    def test_cannot_resume_active_event(self, mock_event_active):
        """Should not be able to resume an already active event."""
        from ctf.services import resume_event

        result = resume_event(mock_event_active)
        assert result is False
        assert mock_event_active.status == EventStatus.ACTIVE.value

    def test_cannot_archive_active_event(self, mock_event_active):
        """Should not be able to archive an active event."""
        from ctf.services import archive_event

        result = archive_event(mock_event_active)
        assert result is False
        assert mock_event_active.status == EventStatus.ACTIVE.value

    def test_cannot_transition_past_ended(self):
        """Ended event cannot go back to active."""
        from ctf.services import activate_event

        ended_event = _make_mock_event(status=EventStatus.ENDED.value)
        result = activate_event(ended_event)
        assert result is False
        assert ended_event.status == EventStatus.ENDED.value

    def test_cannot_transition_from_archived(self):
        """Archived is terminal; no transitions out."""
        from ctf.services import activate_event

        archived_event = _make_mock_event(status=EventStatus.ARCHIVED.value)
        result = activate_event(archived_event)
        assert result is False
        assert archived_event.status == EventStatus.ARCHIVED.value

    def test_cancel_paused_event(self):
        """Should be able to cancel a paused event."""
        from ctf.services import cancel_event

        paused_event = _make_mock_event(status=EventStatus.PAUSED.value)
        with (
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
            patch("ctf.services.event._cancel_event_tasks"),
            patch("ctf.services.range.cleanup_event_ranges"),
        ):
            result = cancel_event(paused_event)
        assert result is True
        assert paused_event.status == EventStatus.CANCELLED.value

    def test_cancel_registration_event(self):
        """Should be able to cancel an event in registration."""
        from ctf.services import cancel_event

        reg_event = _make_mock_event(status=EventStatus.REGISTRATION.value)
        with (
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
            patch("ctf.services.event._cancel_event_tasks"),
            patch("ctf.services.range.cleanup_event_ranges"),
        ):
            result = cancel_event(reg_event)
        assert result is True
        assert reg_event.status == EventStatus.CANCELLED.value

    def test_valid_transitions_covers_all_states(self):
        """Every EventStatus value should be a key in VALID_TRANSITIONS."""
        from ctf.enums import VALID_TRANSITIONS

        for status in EventStatus:
            assert status in VALID_TRANSITIONS, f"{status} missing from VALID_TRANSITIONS"


# ---------------------------------------------------------------------------
# Event Service Tests
# ---------------------------------------------------------------------------


class TestEventServices:
    """Test event service functions with mocked ORM."""

    def test_create_event_service(self, mock_user):
        """create_event service should create event and return it."""
        created_event = _make_mock_event(
            name="Service Created Event",
            status=EventStatus.DRAFT.value,
        )

        with (
            patch("ctf.services.event.CTFEvent.objects") as mock_objects,
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
        ):
            mock_objects.create.return_value = created_event
            from ctf.services import create_event

            event_data = {
                "name": "Service Created Event",
                "description": "Created via service",
                "event_start": timezone.now() + timedelta(days=1),
                "event_end": timezone.now() + timedelta(days=1, hours=8),
                "scenario_id": "basic",
            }
            event = create_event(mock_user, event_data)

        assert event.pk is not None
        assert event.name == "Service Created Event"
        assert event.status == EventStatus.DRAFT.value

    def test_get_organizer_events(self, mock_user, mock_event, mock_event_draft):
        """get_organizer_events should return only organizer's events."""
        qs = MagicMock()
        qs.order_by.return_value = [mock_event, mock_event_draft]

        with patch("ctf.services.event.CTFEvent.objects") as mock_objects:
            mock_objects.filter.return_value = qs
            from ctf.services import get_organizer_events

            events = get_organizer_events(mock_user)

        assert mock_event in events
        assert mock_event_draft in events

    def test_get_organizer_events_excludes_others(self, mock_user, mock_event):
        """get_organizer_events should exclude other organizers' events."""
        other_event = _make_mock_event(
            name="Other Event",
            created_by_id=3,
        )

        qs = MagicMock()
        qs.order_by.return_value = [mock_event]

        with patch("ctf.services.event.CTFEvent.objects") as mock_objects:
            mock_objects.filter.return_value = qs
            from ctf.services import get_organizer_events

            events = get_organizer_events(mock_user)

        assert mock_event in events
        assert other_event not in events

    def test_get_event_returns_event(self, mock_event):
        """get_event should return event by ID."""
        with patch("ctf.services.event.CTFEvent.objects") as mock_objects:
            mock_objects.get.return_value = mock_event
            from ctf.services import get_event

            event = get_event(mock_event.pk)

        assert event == mock_event

    def test_get_event_not_found(self):
        """get_event should raise CTFNotFoundError for nonexistent event."""
        from ctf.exceptions import CTFNotFoundError
        from ctf.models import CTFEvent

        with patch("ctf.services.event.CTFEvent.objects") as mock_objects:
            mock_objects.get.side_effect = CTFEvent.DoesNotExist
            from ctf.services import get_event

            with pytest.raises(CTFNotFoundError):
                get_event(uuid4())

    def test_update_event(self, mock_event_draft):
        """update_event should update event fields."""
        mock_event_draft.is_modifiable = True
        mock_event_draft.event_start = timezone.now() + timedelta(days=7)
        mock_event_draft.event_end = timezone.now() + timedelta(days=7, hours=8)

        with (
            patch("ctf.services.event.CTFEvent.objects") as mock_objects,
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
        ):
            mock_objects.get.return_value = mock_event_draft
            from ctf.services import update_event

            updated = update_event(
                mock_event_draft.pk,
                {"name": "Updated Name", "description": "Updated description"},
            )

        assert updated.name == "Updated Name"
        assert updated.description == "Updated description"

    def test_update_event_blocked_for_terminal(self):
        """update_event should block updates to terminal status events."""
        from ctf.exceptions import CTFStateError

        completed_event = _make_mock_event(
            name="Completed",
            status=EventStatus.ENDED.value,
            is_modifiable=False,
        )

        with patch("ctf.services.event.CTFEvent.objects") as mock_objects:
            mock_objects.get.return_value = completed_event
            from ctf.services import update_event

            with pytest.raises(CTFStateError):
                update_event(completed_event.pk, {"name": "New Name"})


# ---------------------------------------------------------------------------
# Force Delete Service Tests
# ---------------------------------------------------------------------------


class TestForceDeleteEvent:
    """Tests for force_delete_event service function."""

    def test_force_delete_success(self, mock_user):
        """force_delete_event should hard-delete the event and clean up ranges."""
        event = _make_mock_event(name="My CTF")
        event.delete = MagicMock(return_value=(1, {"CTFEvent": 1}))

        with (
            patch("ctf.services.event.CTFEvent.all_objects") as mock_all,
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
            patch("ctf.services.event._cancel_event_tasks") as mock_cancel,
            patch(
                "ctf.services.range.cleanup_event_ranges",
                return_value={"destroyed": 3, "failed": 0},
            ) as mock_cleanup,
        ):
            mock_all.get.return_value = event
            from ctf.services.event import force_delete_event

            result = force_delete_event(event.pk, mock_user, "My CTF")

        assert result["event_name"] == "My CTF"
        assert result["ranges_destroyed"] == 3
        assert result["ranges_failed"] == 0
        event.delete.assert_called_once_with(soft=False)
        mock_cancel.assert_called_once_with(event)
        mock_cleanup.assert_called_once_with(event.pk)

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

        with (
            patch("ctf.services.event.CTFEvent.all_objects") as mock_all,
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
            patch("ctf.services.event._cancel_event_tasks"),
            patch(
                "ctf.services.range.cleanup_event_ranges",
                return_value={"destroyed": 2, "failed": 1},
            ),
        ):
            mock_all.get.return_value = event
            from ctf.services.event import force_delete_event

            result = force_delete_event(event.pk, mock_user, "Partial Fail")

        assert result["ranges_destroyed"] == 2
        assert result["ranges_failed"] == 1
        event.delete.assert_called_once_with(soft=False)

    def test_force_delete_range_cleanup_total_failure(self, mock_user):
        """force_delete_event should proceed even if range cleanup raises."""
        event = _make_mock_event(name="Total Fail")
        event.delete = MagicMock(return_value=(1, {"CTFEvent": 1}))

        with (
            patch("ctf.services.event.CTFEvent.all_objects") as mock_all,
            patch("ctf.services.event.transaction.atomic", side_effect=_noop_atomic),
            patch("ctf.services.event._cancel_event_tasks"),
            patch(
                "ctf.services.range.cleanup_event_ranges",
                side_effect=RuntimeError("CMS bridge down"),
            ),
        ):
            mock_all.get.return_value = event
            from ctf.services.event import force_delete_event

            result = force_delete_event(event.pk, mock_user, "Total Fail")

        assert result["ranges_destroyed"] == 0
        assert result["ranges_failed"] == 0
        event.delete.assert_called_once_with(soft=False)


# ---------------------------------------------------------------------------
# Force Delete API Tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Force Delete Admin View Tests
# ---------------------------------------------------------------------------


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
