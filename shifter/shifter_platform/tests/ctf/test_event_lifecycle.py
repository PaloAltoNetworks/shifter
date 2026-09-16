"""Tests for CTF Event Management - Phase 3.

Tests cover:
- Event form validation
- Event list view (filtering, pagination)
- Event create view
- Event detail view
- Event edit view
- Event status transitions (schedule, activate, complete, cancel)
- Event services

Legacy view tests mock the ORM; lifecycle persistence tests use real model rows.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from ctf.enums import EventStatus

# ---------------------------------------------------------------------------
# Shared mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_user():
    """Create a mock authenticated user (organizer)."""
    from shared.auth import CTF_ORGANIZER_GROUP

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
    # Drive the real get_user_role via group membership (the public
    # get_user_group_names contract) instead of patching first-party topology.
    user.groups.values_list.return_value = [CTF_ORGANIZER_GROUP]
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
    # No CTF groups -> real get_user_role reports neither organizer nor participant.
    user.groups.values_list.return_value = []
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


def _make_db_event(organizer_user, status, name="Lifecycle Event", **overrides):
    """Create a real CTFEvent in the given status for behavioral transition tests."""
    from ctf.models import CTFEvent

    fields = {
        "name": name,
        "description": "Behavioral lifecycle test event",
        "created_by": organizer_user,
        "status": status,
        "event_start": timezone.now() + timedelta(days=1),
        "event_end": timezone.now() + timedelta(days=1, hours=8),
        "scenario_id": "basic",
        "auto_cleanup": False,
    }
    fields.update(overrides)
    return CTFEvent.objects.create(**fields)


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
        patch("django.contrib.auth.get_user", return_value=mock_user),
        patch("django.contrib.auth.middleware.get_user", return_value=mock_user),
        patch("ctf.context_processors.ctf_navigation", return_value=ctx_proc_defaults),
        patch("mission_control.context_processors.active_range", return_value=range_ctx_defaults),
        patch("config.context_processors.user_permissions", return_value={"can_access_threat_research": False}),
    ):
        yield


@pytest.fixture
def _mock_auth_standard(mock_standard_user):
    """Patch Django auth to authenticate mock_standard_user as non-organizer."""
    with (
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


class TestEventStatusTransitions:
    """Test event status transitions via service functions.

    These test the pure business logic: status guards and field mutation.
    ORM .save() and .refresh_from_db() are mocked on the event objects.
    """

    @pytest.mark.django_db
    def test_schedule_draft_event(self, organizer_user):
        """Scheduling a draft event opens registration and creates its tasks."""
        from ctf.models import CTFScheduledTask
        from ctf.services import schedule_event

        event = _make_db_event(organizer_user, EventStatus.DRAFT.value)
        result = schedule_event(event)

        assert result is True
        event.refresh_from_db()
        assert event.status == EventStatus.REGISTRATION.value
        # Observable side effect of scheduling: lifecycle automation tasks exist.
        assert CTFScheduledTask.objects.filter(event=event).exists()

    @pytest.mark.django_db
    def test_activate_scheduled_event(self, organizer_user):
        """Should be able to activate a scheduled event."""
        from ctf.services import activate_event

        event = _make_db_event(organizer_user, EventStatus.REGISTRATION.value)
        result = activate_event(event)
        assert result is True
        event.refresh_from_db()
        assert event.status == EventStatus.ACTIVE.value

    @pytest.mark.django_db
    def test_complete_active_event(self, organizer_user):
        """Should be able to complete an active event.

        Real-DB (not mocked): completing an event finalizes the materialized
        leaderboard from the database (issue #850), so this asserts the
        observable status transition rather than mocking that first-party call.
        """
        from ctf.models import CTFEvent
        from ctf.services import complete_event

        event = CTFEvent.objects.create(
            name="Active CTF Event",
            description="An active event",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
            auto_cleanup=False,
        )
        result = complete_event(event)
        assert result is True
        event.refresh_from_db()
        assert event.status == EventStatus.ENDED.value

    @pytest.mark.django_db
    def test_cancel_draft_event(self, organizer_user):
        """Should be able to cancel a draft event."""
        with patch("ctf.services.range.cleanup_event_ranges"):
            from ctf.services import cancel_event

            event = _make_db_event(organizer_user, EventStatus.DRAFT.value)
            result = cancel_event(event)
        assert result is True
        event.refresh_from_db()
        assert event.status == EventStatus.CANCELLED.value

    @pytest.mark.django_db
    def test_cancel_scheduled_event(self, organizer_user):
        """Cancelling a scheduled event cancels its pending automation tasks."""
        from ctf.enums import ScheduledTaskStatus
        from ctf.models import CTFScheduledTask
        from ctf.services import cancel_event, schedule_event

        event = _make_db_event(organizer_user, EventStatus.DRAFT.value)
        schedule_event(event)
        assert CTFScheduledTask.objects.filter(event=event, status=ScheduledTaskStatus.PENDING.value).exists()

        with patch("ctf.services.range.cleanup_event_ranges"):
            result = cancel_event(event)

        assert result is True
        event.refresh_from_db()
        assert event.status == EventStatus.CANCELLED.value
        assert not CTFScheduledTask.objects.filter(event=event, status=ScheduledTaskStatus.PENDING.value).exists()

    @pytest.mark.django_db
    def test_cannot_activate_draft_event(self, organizer_user):
        """Should not be able to activate a draft event directly."""
        from ctf.services import activate_event

        event = _make_db_event(organizer_user, EventStatus.DRAFT.value)
        result = activate_event(event)
        assert result is False
        event.refresh_from_db()
        assert event.status == EventStatus.DRAFT.value

    def test_cannot_schedule_active_event(self, mock_event_active):
        """Should not be able to schedule an active event."""
        from ctf.services import schedule_event

        result = schedule_event(mock_event_active)
        assert result is False

    @pytest.mark.django_db
    def test_cannot_modify_ended_event(self, organizer_user):
        """Real `CTFEvent.is_modifiable`: terminal (ended) events are not modifiable."""
        from ctf.models import CTFEvent

        ended_event = CTFEvent.objects.create(
            name="Ended",
            created_by=organizer_user,
            status=EventStatus.ENDED.value,
            event_start=timezone.now() - timedelta(hours=2),
            event_end=timezone.now() - timedelta(hours=1),
            scenario_id="basic",
        )
        draft_event = CTFEvent.objects.create(
            name="Draft",
            created_by=organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
            scenario_id="basic",
        )
        assert ended_event.is_modifiable is False
        assert draft_event.is_modifiable is True

    def test_pause_active_event(self, mock_event_active):
        """Should be able to pause an active event."""
        from ctf.services import pause_event

        result = pause_event(mock_event_active)
        assert result is True
        assert mock_event_active.status == EventStatus.PAUSED.value
        mock_event_active.save.assert_called_once()

    @pytest.mark.django_db
    def test_resume_paused_event(self, organizer_user):
        """Should be able to resume a paused event.

        ``resume_event`` locks the row and re-enforces managed-content
        readiness under the lock (issue #1971), so this is DB-backed; an
        unmanaged event with no configured reference is ready.
        """
        from ctf.services import resume_event

        event = _make_db_event(organizer_user, EventStatus.PAUSED.value)
        result = resume_event(event)
        assert result is True
        event.refresh_from_db()
        assert event.status == EventStatus.ACTIVE.value

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

    @pytest.mark.django_db
    def test_cannot_resume_active_event(self, organizer_user):
        """Should not be able to resume an already active event."""
        from ctf.services import resume_event

        event = _make_db_event(organizer_user, EventStatus.ACTIVE.value)
        result = resume_event(event)
        assert result is False
        event.refresh_from_db()
        assert event.status == EventStatus.ACTIVE.value

    def test_cannot_archive_active_event(self, mock_event_active):
        """Should not be able to archive an active event."""
        from ctf.services import archive_event

        result = archive_event(mock_event_active)
        assert result is False
        assert mock_event_active.status == EventStatus.ACTIVE.value

    @pytest.mark.django_db
    def test_cannot_transition_past_ended(self, organizer_user):
        """Ended event cannot go back to active."""
        from ctf.services import activate_event

        ended_event = _make_db_event(organizer_user, EventStatus.ENDED.value)
        result = activate_event(ended_event)
        assert result is False
        ended_event.refresh_from_db()
        assert ended_event.status == EventStatus.ENDED.value

    @pytest.mark.django_db
    def test_cannot_transition_from_archived(self, organizer_user):
        """Archived is terminal; no transitions out."""
        from ctf.services import activate_event

        archived_event = _make_db_event(organizer_user, EventStatus.ARCHIVED.value)
        result = activate_event(archived_event)
        assert result is False
        archived_event.refresh_from_db()
        assert archived_event.status == EventStatus.ARCHIVED.value

    @pytest.mark.django_db
    def test_cancel_paused_event(self, organizer_user):
        """Should be able to cancel a paused event."""
        from ctf.services import cancel_event

        paused_event = _make_db_event(organizer_user, EventStatus.PAUSED.value)
        with patch("ctf.services.range.cleanup_event_ranges"):
            result = cancel_event(paused_event)
        assert result is True
        paused_event.refresh_from_db()
        assert paused_event.status == EventStatus.CANCELLED.value

    @pytest.mark.django_db
    def test_cancel_registration_event(self, organizer_user):
        """Should be able to cancel an event in registration."""
        from ctf.services import cancel_event

        reg_event = _make_db_event(organizer_user, EventStatus.REGISTRATION.value)
        with patch("ctf.services.range.cleanup_event_ranges"):
            result = cancel_event(reg_event)
        assert result is True
        reg_event.refresh_from_db()
        assert reg_event.status == EventStatus.CANCELLED.value

    def test_valid_transitions_covers_all_states(self):
        """Every EventStatus value should be a key in VALID_TRANSITIONS."""
        from ctf.enums import VALID_TRANSITIONS

        for status in EventStatus:
            assert status in VALID_TRANSITIONS, f"{status} missing from VALID_TRANSITIONS"


class TestEventServices:
    """Test event service functions.

    Service behavior (filter predicates, forced-DRAFT invariant, mass-assignment
    guard, cross-organizer isolation) is exercised against real DB rows; pure
    transition guards that need no DB stay mocked above.
    """

    @pytest.mark.django_db
    def test_create_event_service(self, organizer_user):
        """create_event persists the event, forces DRAFT, and blocks mass assignment."""
        from ctf.models import CTFEvent
        from ctf.services import create_event

        event = create_event(
            organizer_user,
            {
                "name": "Service Created Event",
                "description": "Created via service",
                "event_start": timezone.now() + timedelta(days=1),
                "event_end": timezone.now() + timedelta(days=1, hours=8),
                "scenario_id": "basic",
                # Mass-assignment attempts that the service must ignore.
                "status": EventStatus.ACTIVE.value,
                "created_by_id": 999999,
            },
        )

        assert event.pk is not None
        assert event.name == "Service Created Event"
        # Status is forced to DRAFT regardless of the supplied value, and
        # created_by is the caller, not the injected id.
        assert event.status == EventStatus.DRAFT.value
        assert event.created_by_id == organizer_user.pk
        # Same invariants hold for the persisted row.
        persisted = CTFEvent.objects.get(pk=event.pk)
        assert persisted.status == EventStatus.DRAFT.value
        assert persisted.created_by_id == organizer_user.pk

    @pytest.mark.django_db
    def test_get_organizer_events(self, organizer_user):
        """get_organizer_events returns the organizer's own events."""
        from ctf.models import CTFEvent
        from ctf.services import get_organizer_events

        e1 = CTFEvent.objects.create(
            name="E1",
            created_by=organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
            scenario_id="basic",
        )
        e2 = CTFEvent.objects.create(
            name="E2",
            created_by=organizer_user,
            status=EventStatus.REGISTRATION.value,
            event_start=timezone.now() + timedelta(days=2),
            event_end=timezone.now() + timedelta(days=2, hours=8),
            scenario_id="basic",
        )

        events = list(get_organizer_events(organizer_user))
        assert {e.pk for e in events} == {e1.pk, e2.pk}

    @pytest.mark.django_db
    def test_get_organizer_events_excludes_others(self, organizer_user, standard_user):
        """get_organizer_events filters by created_by — no cross-organizer leakage.

        Regression guard: dropping `filter(created_by=user)` would leak another
        user's events here, where the mocked version could not catch it.
        """
        from ctf.models import CTFEvent
        from ctf.services import get_organizer_events

        mine = CTFEvent.objects.create(
            name="Mine",
            created_by=organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
            scenario_id="basic",
        )
        theirs = CTFEvent.objects.create(
            name="Theirs",
            created_by=standard_user,
            status=EventStatus.DRAFT.value,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
            scenario_id="basic",
        )

        pks = {e.pk for e in get_organizer_events(organizer_user)}
        assert mine.pk in pks
        assert theirs.pk not in pks

    def test_get_organizer_events_filters_by_status(self, organizer_user):
        """get_organizer_events(status=...) applies the status filter against real rows.

        Regression guard for the admin_event_list ``?status=`` path: dropping
        ``filter(status=status)`` would leak the active event into a draft-only
        query here, where the view test that mocks the service could not catch it.
        """
        from ctf.models import CTFEvent
        from ctf.services import get_organizer_events

        draft = CTFEvent.objects.create(
            name="Draft one",
            created_by=organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
            scenario_id="basic",
        )
        active = CTFEvent.objects.create(
            name="Active one",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
            scenario_id="basic",
        )

        draft_pks = {e.pk for e in get_organizer_events(organizer_user, status=EventStatus.DRAFT.value)}
        assert draft.pk in draft_pks
        assert active.pk not in draft_pks

    @pytest.mark.django_db
    def test_get_event_returns_event(self, organizer_user):
        """get_event should return event by ID."""
        from ctf.services import get_event

        created = _make_db_event(organizer_user, EventStatus.REGISTRATION.value)
        assert get_event(created.pk) == created

    @pytest.mark.django_db
    def test_get_event_not_found(self):
        """get_event should raise CTFNotFoundError for nonexistent event."""
        from ctf.exceptions import CTFNotFoundError
        from ctf.services import get_event

        missing_id = uuid4()
        with pytest.raises(CTFNotFoundError):
            get_event(missing_id)

    @pytest.mark.django_db
    def test_update_event(self, organizer_user):
        """update_event should update and persist event fields."""
        from ctf.services import update_event

        event = _make_db_event(organizer_user, EventStatus.DRAFT.value)
        updated = update_event(
            event.pk,
            {"name": "Updated Name", "description": "Updated description"},
        )

        assert updated.name == "Updated Name"
        event.refresh_from_db()
        assert event.name == "Updated Name"
        assert event.description == "Updated description"

    @pytest.mark.django_db
    def test_update_event_blocked_for_terminal(self, organizer_user):
        """update_event should block updates to terminal status events."""
        from ctf.exceptions import CTFStateError
        from ctf.services import update_event

        completed_event = _make_db_event(organizer_user, EventStatus.ENDED.value, name="Completed")
        with pytest.raises(CTFStateError):
            update_event(completed_event.pk, {"name": "New Name"})
        completed_event.refresh_from_db()
        assert completed_event.name == "Completed"
