"""Tests for CTF Event Management - Phase 3.

Tests cover:
- Event form validation
- Event list view (filtering, pagination)
- Event create view
- Event detail view
- Event edit view
- Event status transitions (schedule, activate, complete, cancel)
- Event services
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from ctf.enums import EventStatus
from ctf.models import CTFEvent

if TYPE_CHECKING:
    from django.test import Client


# ---------------------------------------------------------------------------
# Form Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFEventForm:
    """Test CTFEventForm validation."""

    def test_form_valid_minimal_data(self, organizer_user):
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
        }
        form = CTFEventForm(data=data)
        assert form.is_valid(), form.errors

    def test_form_valid_team_mode(self, organizer_user):
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
        }
        form = CTFEventForm(data=data)
        assert form.is_valid(), form.errors

    def test_form_invalid_end_before_start(self, organizer_user):
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

    def test_form_invalid_team_mode_without_size(self, organizer_user):
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

    def test_form_invalid_registration_deadline_after_start(self, organizer_user):
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

    def test_form_with_optional_fields(self, organizer_user):
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
        }
        form = CTFEventForm(data=data)
        assert form.is_valid(), form.errors


# ---------------------------------------------------------------------------
# Event List View Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventListView:
    """Test event list view for organizers."""

    def test_event_list_requires_login(self, client: Client):
        """Event list should require authentication."""
        response = client.get(reverse("ctf:admin_event_list"))
        assert response.status_code == 302  # Redirect to login

    def test_event_list_requires_organizer(self, authenticated_standard_client: Client):
        """Event list should require organizer role."""
        response = authenticated_standard_client.get(reverse("ctf:admin_event_list"))
        assert response.status_code == 403

    def test_event_list_shows_organizer_events(self, authenticated_organizer_client: Client, ctf_event, organizer_user):
        """Organizer should see their own events."""
        response = authenticated_organizer_client.get(reverse("ctf:admin_event_list"))
        assert response.status_code == 200
        assert ctf_event.name in response.content.decode()

    def test_event_list_filter_by_status(
        self, authenticated_organizer_client: Client, ctf_event, ctf_event_draft, organizer_user
    ):
        """Event list should filter by status."""
        response = authenticated_organizer_client.get(reverse("ctf:admin_event_list") + "?status=draft")
        assert response.status_code == 200
        content = response.content.decode()
        assert ctf_event_draft.name in content
        assert ctf_event.name not in content

    def test_event_list_shows_all_statuses_by_default(
        self, authenticated_organizer_client: Client, ctf_event, ctf_event_draft, organizer_user
    ):
        """Event list should show all events by default."""
        response = authenticated_organizer_client.get(reverse("ctf:admin_event_list"))
        assert response.status_code == 200
        content = response.content.decode()
        assert ctf_event.name in content
        assert ctf_event_draft.name in content

    def test_event_list_hides_other_organizer_events(
        self, authenticated_organizer_client: Client, second_organizer_user, db
    ):
        """Organizer should not see other organizers' events."""
        other_event = CTFEvent.objects.create(
            name="Other Organizer Event",
            description="Not mine",
            created_by=second_organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=timezone.now() + timedelta(days=5),
            event_end=timezone.now() + timedelta(days=5, hours=8),
            scenario_id="basic",
        )
        response = authenticated_organizer_client.get(reverse("ctf:admin_event_list"))
        assert response.status_code == 200
        assert other_event.name not in response.content.decode()


# ---------------------------------------------------------------------------
# Event Create View Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventCreateView:
    """Test event creation view."""

    def test_create_view_requires_login(self, client: Client):
        """Create view should require authentication."""
        response = client.get(reverse("ctf:admin_event_create"))
        assert response.status_code == 302

    def test_create_view_requires_organizer(self, authenticated_standard_client: Client):
        """Create view should require organizer role."""
        response = authenticated_standard_client.get(reverse("ctf:admin_event_create"))
        assert response.status_code == 403

    def test_create_view_renders_form(self, authenticated_organizer_client: Client):
        """Create view should render the AJAX form template with scenarios."""
        response = authenticated_organizer_client.get(reverse("ctf:admin_event_create"))
        assert response.status_code == 200
        assert "scenarios_json" in response.context

    def test_create_view_is_get_only(self, authenticated_organizer_client: Client):
        """Create view should reject POST (form submission is via API now)."""
        response = authenticated_organizer_client.post(reverse("ctf:admin_event_create"), data={})
        assert response.status_code == 405


# ---------------------------------------------------------------------------
# Event Detail View Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventDetailView:
    """Test event detail view."""

    def test_detail_view_requires_login(self, client: Client, ctf_event):
        """Detail view should require authentication."""
        response = client.get(reverse("ctf:admin_event_detail", kwargs={"event_id": ctf_event.pk}))
        assert response.status_code == 302

    def test_detail_view_requires_organizer(self, authenticated_standard_client: Client, ctf_event):
        """Detail view should require organizer role."""
        response = authenticated_standard_client.get(
            reverse("ctf:admin_event_detail", kwargs={"event_id": ctf_event.pk})
        )
        assert response.status_code == 403

    def test_detail_view_shows_event(self, authenticated_organizer_client: Client, ctf_event):
        """Detail view should show event information."""
        response = authenticated_organizer_client.get(
            reverse("ctf:admin_event_detail", kwargs={"event_id": ctf_event.pk})
        )
        assert response.status_code == 200
        assert ctf_event.name in response.content.decode()

    def test_detail_view_shows_stats(
        self, authenticated_organizer_client: Client, ctf_event, ctf_challenge, ctf_participant
    ):
        """Detail view should show event statistics."""
        response = authenticated_organizer_client.get(
            reverse("ctf:admin_event_detail", kwargs={"event_id": ctf_event.pk})
        )
        assert response.status_code == 200
        # Stats should be in context
        assert "event" in response.context

    def test_detail_view_404_for_nonexistent(self, authenticated_organizer_client: Client):
        """Detail view should 404 for nonexistent event."""
        from uuid import uuid4

        response = authenticated_organizer_client.get(reverse("ctf:admin_event_detail", kwargs={"event_id": uuid4()}))
        assert response.status_code == 404

    def test_detail_view_403_for_other_organizer_event(
        self, authenticated_organizer_client: Client, second_organizer_user, db
    ):
        """Organizer should not access other organizer's event."""
        other_event = CTFEvent.objects.create(
            name="Other Event",
            description="Not mine",
            created_by=second_organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=timezone.now() + timedelta(days=5),
            event_end=timezone.now() + timedelta(days=5, hours=8),
            scenario_id="basic",
        )
        response = authenticated_organizer_client.get(
            reverse("ctf:admin_event_detail", kwargs={"event_id": other_event.pk})
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Event Edit View Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventEditView:
    """Test event edit view."""

    def test_edit_view_requires_login(self, client: Client, ctf_event):
        """Edit view should require authentication."""
        response = client.get(reverse("ctf:admin_event_edit", kwargs={"event_id": ctf_event.pk}))
        assert response.status_code == 302

    def test_edit_view_requires_organizer(self, authenticated_standard_client: Client, ctf_event):
        """Edit view should require organizer role."""
        response = authenticated_standard_client.get(reverse("ctf:admin_event_edit", kwargs={"event_id": ctf_event.pk}))
        assert response.status_code == 403

    def test_edit_view_renders_form_with_data(self, authenticated_organizer_client: Client, ctf_event_draft):
        """Edit view should render AJAX form template with scenarios and event_id."""
        response = authenticated_organizer_client.get(
            reverse("ctf:admin_event_edit", kwargs={"event_id": ctf_event_draft.pk})
        )
        assert response.status_code == 200
        assert "scenarios_json" in response.context
        assert response.context["is_edit"] is True
        assert response.context["event_id"] == str(ctf_event_draft.pk)

    def test_edit_view_is_get_only(self, authenticated_organizer_client: Client, ctf_event_draft):
        """Edit view should reject POST (form submission is via API now)."""
        response = authenticated_organizer_client.post(
            reverse("ctf:admin_event_edit", kwargs={"event_id": ctf_event_draft.pk}),
            data={},
        )
        assert response.status_code == 405

    def test_edit_completed_event_blocked(self, authenticated_organizer_client: Client, organizer_user, db):
        """Editing a completed event should be blocked."""
        completed_event = CTFEvent.objects.create(
            name="Completed Event",
            description="Already done",
            created_by=organizer_user,
            status=EventStatus.COMPLETED.value,
            event_start=timezone.now() - timedelta(days=2),
            event_end=timezone.now() - timedelta(days=1),
            scenario_id="basic",
        )
        response = authenticated_organizer_client.get(
            reverse("ctf:admin_event_edit", kwargs={"event_id": completed_event.pk})
        )
        # Should redirect or show error
        assert response.status_code in (302, 403)


# ---------------------------------------------------------------------------
# Event Status Transition Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventStatusTransitions:
    """Test event status transitions via API."""

    def test_schedule_draft_event(self, authenticated_organizer_client: Client, ctf_event_draft):
        """Should be able to schedule a draft event."""
        from ctf.services import schedule_event

        result = schedule_event(ctf_event_draft)
        assert result is True
        ctf_event_draft.refresh_from_db()
        assert ctf_event_draft.status == EventStatus.SCHEDULED.value

    def test_activate_scheduled_event(self, authenticated_organizer_client: Client, ctf_event):
        """Should be able to activate a scheduled event."""
        from ctf.services import activate_event

        result = activate_event(ctf_event)
        assert result is True
        ctf_event.refresh_from_db()
        assert ctf_event.status == EventStatus.ACTIVE.value

    def test_complete_active_event(self, authenticated_organizer_client: Client, ctf_event_active):
        """Should be able to complete an active event."""
        from ctf.services import complete_event

        result = complete_event(ctf_event_active)
        assert result is True
        ctf_event_active.refresh_from_db()
        assert ctf_event_active.status == EventStatus.COMPLETED.value

    def test_cancel_draft_event(self, authenticated_organizer_client: Client, ctf_event_draft):
        """Should be able to cancel a draft event."""
        from ctf.services import cancel_event

        result = cancel_event(ctf_event_draft)
        assert result is True
        ctf_event_draft.refresh_from_db()
        assert ctf_event_draft.status == EventStatus.CANCELLED.value

    def test_cancel_scheduled_event(self, authenticated_organizer_client: Client, ctf_event):
        """Should be able to cancel a scheduled event."""
        from ctf.services import cancel_event

        result = cancel_event(ctf_event)
        assert result is True
        ctf_event.refresh_from_db()
        assert ctf_event.status == EventStatus.CANCELLED.value

    def test_cannot_activate_draft_event(self, authenticated_organizer_client: Client, ctf_event_draft):
        """Should not be able to activate a draft event directly."""
        from ctf.services import activate_event

        result = activate_event(ctf_event_draft)
        assert result is False
        ctf_event_draft.refresh_from_db()
        assert ctf_event_draft.status == EventStatus.DRAFT.value

    def test_cannot_schedule_active_event(self, authenticated_organizer_client: Client, ctf_event_active):
        """Should not be able to schedule an active event."""
        from ctf.services import schedule_event

        result = schedule_event(ctf_event_active)
        assert result is False

    def test_cannot_modify_completed_event(self, authenticated_organizer_client: Client, organizer_user, db):
        """Completed events should not be modifiable."""
        completed_event = CTFEvent.objects.create(
            name="Completed",
            description="Done",
            created_by=organizer_user,
            status=EventStatus.COMPLETED.value,
            event_start=timezone.now() - timedelta(days=2),
            event_end=timezone.now() - timedelta(days=1),
            scenario_id="basic",
        )
        assert completed_event.is_modifiable is False


# ---------------------------------------------------------------------------
# Event Service Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventServices:
    """Test event service functions."""

    def test_create_event_service(self, organizer_user):
        """create_event service should create event and return it."""
        from ctf.services import create_event

        event_data = {
            "name": "Service Created Event",
            "description": "Created via service",
            "event_start": timezone.now() + timedelta(days=1),
            "event_end": timezone.now() + timedelta(days=1, hours=8),
            "scenario_id": "basic",
        }
        event = create_event(organizer_user, event_data)
        assert event.pk is not None
        assert event.name == "Service Created Event"
        assert event.status == EventStatus.DRAFT.value

    def test_get_organizer_events(self, organizer_user, ctf_event, ctf_event_draft):
        """get_organizer_events should return only organizer's events."""
        from ctf.services import get_organizer_events

        events = get_organizer_events(organizer_user)
        assert ctf_event in events
        assert ctf_event_draft in events

    def test_get_organizer_events_excludes_others(self, organizer_user, second_organizer_user, ctf_event, db):
        """get_organizer_events should exclude other organizers' events."""
        from ctf.services import get_organizer_events

        other_event = CTFEvent.objects.create(
            name="Other Event",
            description="Not mine",
            created_by=second_organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=timezone.now() + timedelta(days=5),
            event_end=timezone.now() + timedelta(days=5, hours=8),
            scenario_id="basic",
        )

        events = get_organizer_events(organizer_user)
        assert ctf_event in events
        assert other_event not in events

    def test_get_event_returns_event(self, ctf_event):
        """get_event should return event by ID."""
        from ctf.services import get_event

        event = get_event(ctf_event.pk)
        assert event == ctf_event

    def test_get_event_not_found(self):
        """get_event should raise CTFNotFoundError for nonexistent event."""
        from uuid import uuid4

        from ctf.exceptions import CTFNotFoundError
        from ctf.services import get_event

        with pytest.raises(CTFNotFoundError):
            get_event(uuid4())

    def test_update_event(self, ctf_event_draft):
        """update_event should update event fields."""
        from ctf.services import update_event

        updated = update_event(
            ctf_event_draft.pk,
            {"name": "Updated Name", "description": "Updated description"},
        )
        assert updated.name == "Updated Name"
        assert updated.description == "Updated description"

    def test_update_event_blocked_for_terminal(self, organizer_user, db):
        """update_event should block updates to terminal status events."""
        from ctf.exceptions import CTFStateError
        from ctf.services import update_event

        completed_event = CTFEvent.objects.create(
            name="Completed",
            description="Done",
            created_by=organizer_user,
            status=EventStatus.COMPLETED.value,
            event_start=timezone.now() - timedelta(days=2),
            event_end=timezone.now() - timedelta(days=1),
            scenario_id="basic",
        )

        with pytest.raises(CTFStateError):
            update_event(completed_event.pk, {"name": "New Name"})
