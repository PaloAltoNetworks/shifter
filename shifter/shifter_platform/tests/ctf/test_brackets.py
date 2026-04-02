"""Tests for CTF bracket feature (CTF-405).

Tests covering:
- CTFBracket model creation and constraints
- Bracket service CRUD and assignment
- Bracket-filtered scoreboards
- Bracket views and API endpoints
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import django.db
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from ctf.enums import EventStatus, ParticipantStatus
from ctf.models import CTFBracket, CTFEvent, CTFParticipant

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ctf_event_with_brackets(db, organizer_user):
    """Create an active event with brackets."""
    event = CTFEvent.objects.create(
        name="Bracket CTF Event",
        description="Event with brackets",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
    )
    return event


@pytest.fixture
def brackets(db, ctf_event_with_brackets):
    """Create beginner, intermediate, advanced brackets."""
    event = ctf_event_with_brackets
    beginner = CTFBracket.objects.create(
        event=event,
        name="Beginner",
        description="For newcomers",
        display_order=0,
    )
    intermediate = CTFBracket.objects.create(
        event=event,
        name="Intermediate",
        description="Some experience",
        display_order=1,
    )
    advanced = CTFBracket.objects.create(
        event=event,
        name="Advanced",
        description="Experienced players",
        display_order=2,
    )
    return beginner, intermediate, advanced


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------


class TestCTFBracketModel:
    """Tests for the CTFBracket model."""

    def test_create_bracket(self, db, ctf_event_with_brackets):
        """Bracket can be created with event, name, and display_order."""
        bracket = CTFBracket.objects.create(
            event=ctf_event_with_brackets,
            name="Beginner",
            display_order=0,
        )
        assert bracket.name == "Beginner"
        assert bracket.event == ctf_event_with_brackets
        assert bracket.display_order == 0
        assert bracket.description == ""

    def test_bracket_str(self, db, ctf_event_with_brackets):
        """Bracket __str__ returns the name."""
        bracket = CTFBracket.objects.create(
            event=ctf_event_with_brackets,
            name="Advanced",
        )
        assert str(bracket) == "Advanced"

    def test_bracket_ordering(self, brackets):
        """Brackets are ordered by display_order then name."""
        beginner, intermediate, advanced = brackets
        result = list(CTFBracket.objects.filter(event=beginner.event))
        assert result == [beginner, intermediate, advanced]

    def test_unique_name_per_event(self, db, ctf_event_with_brackets):
        """Duplicate bracket names within same event are rejected."""
        CTFBracket.objects.create(
            event=ctf_event_with_brackets,
            name="Beginner",
        )
        with pytest.raises((ValidationError, django.db.IntegrityError)):
            CTFBracket.objects.create(
                event=ctf_event_with_brackets,
                name="Beginner",
            )

    def test_same_name_different_events(self, db, organizer_user):
        """Same bracket name is allowed across different events."""
        event1 = CTFEvent.objects.create(
            name="Event 1",
            created_by=organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
            scenario_id="basic",
        )
        event2 = CTFEvent.objects.create(
            name="Event 2",
            created_by=organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=timezone.now() + timedelta(days=2),
            event_end=timezone.now() + timedelta(days=2, hours=8),
            scenario_id="basic",
        )
        b1 = CTFBracket.objects.create(event=event1, name="Beginner")
        b2 = CTFBracket.objects.create(event=event2, name="Beginner")
        assert b1.name == b2.name
        assert b1.event != b2.event

    def test_soft_delete(self, brackets):
        """Soft-deleted bracket allows re-creation of same name."""
        beginner, _, _ = brackets
        event = beginner.event
        beginner.delete()
        assert beginner.deleted_at is not None
        # Can create new bracket with same name
        new_beginner = CTFBracket.objects.create(event=event, name="Beginner")
        assert new_beginner.pk != beginner.pk

    def test_participant_count_property(self, db, ctf_event_with_brackets, participant_user):
        """participant_count returns correct count."""
        bracket = CTFBracket.objects.create(
            event=ctf_event_with_brackets,
            name="Test",
        )
        assert bracket.participant_count == 0
        CTFParticipant.objects.create(
            event=ctf_event_with_brackets,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
            bracket=bracket,
        )
        assert bracket.participant_count == 1


# ---------------------------------------------------------------------------
# Service Tests
# ---------------------------------------------------------------------------


class TestBracketService:
    """Tests for bracket service functions."""

    def test_create_bracket(self, db, ctf_event_with_brackets):
        """create_bracket creates and returns a bracket."""
        from ctf.services.bracket import create_bracket

        bracket = create_bracket(
            event_id=ctf_event_with_brackets.id,
            name="Beginner",
            description="New players",
            display_order=0,
        )
        assert bracket.pk is not None
        assert bracket.name == "Beginner"
        assert bracket.event_id == ctf_event_with_brackets.id

    def test_update_bracket(self, brackets):
        """update_bracket updates allowed fields."""
        from ctf.services.bracket import update_bracket

        beginner, _, _ = brackets
        updated = update_bracket(beginner.id, name="Novice", display_order=5)
        assert updated.name == "Novice"
        assert updated.display_order == 5

    def test_delete_bracket_unassigns_participants(self, db, ctf_event_with_brackets, participant_user):
        """delete_bracket soft-deletes and unassigns participants."""
        from ctf.services.bracket import create_bracket, delete_bracket

        bracket = create_bracket(ctf_event_with_brackets.id, "Beginner")
        participant = CTFParticipant.objects.create(
            event=ctf_event_with_brackets,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
            bracket=bracket,
        )
        delete_bracket(bracket.id)
        participant.refresh_from_db()
        assert participant.bracket is None

    def test_list_brackets(self, brackets):
        """list_brackets returns all brackets for event."""
        from ctf.services.bracket import list_brackets

        beginner, _, _ = brackets
        result = list(list_brackets(beginner.event_id))
        assert len(result) == 3

    def test_get_bracket(self, brackets):
        """get_bracket returns the bracket."""
        from ctf.services.bracket import get_bracket

        beginner, _, _ = brackets
        result = get_bracket(beginner.id)
        assert result.id == beginner.id

    def test_assign_participant_bracket(self, db, ctf_event_with_brackets, participant_user):
        """assign_participant_bracket sets bracket on participant."""
        from ctf.services.bracket import assign_participant_bracket, create_bracket

        bracket = create_bracket(ctf_event_with_brackets.id, "Beginner")
        participant = CTFParticipant.objects.create(
            event=ctf_event_with_brackets,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        result = assign_participant_bracket(participant.id, bracket.id)
        assert result.bracket_id == bracket.id

    def test_assign_bracket_wrong_event(self, db, organizer_user, participant_user):
        """assign_participant_bracket rejects cross-event assignment."""
        from ctf.services.bracket import assign_participant_bracket, create_bracket

        event1 = CTFEvent.objects.create(
            name="Event 1",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
        )
        event2 = CTFEvent.objects.create(
            name="Event 2",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
        )
        bracket = create_bracket(event1.id, "Beginner")
        participant = CTFParticipant.objects.create(
            event=event2,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        with pytest.raises(ValidationError, match="same event"):
            assign_participant_bracket(participant.id, bracket.id)

    def test_remove_participant_bracket(self, db, ctf_event_with_brackets, participant_user):
        """remove_participant_bracket clears bracket assignment."""
        from ctf.services.bracket import (
            assign_participant_bracket,
            create_bracket,
            remove_participant_bracket,
        )

        bracket = create_bracket(ctf_event_with_brackets.id, "Beginner")
        participant = CTFParticipant.objects.create(
            event=ctf_event_with_brackets,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        assign_participant_bracket(participant.id, bracket.id)
        result = remove_participant_bracket(participant.id)
        assert result.bracket is None


# ---------------------------------------------------------------------------
# Scoring Tests
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _make_participant(
    name: str,
    computed_score: int = 0,
    solve_count: int = 0,
    last_solve_time: datetime | None = None,
    team: MagicMock | None = None,
    bracket: MagicMock | None = None,
    pid: str | None = None,
) -> MagicMock:
    """Build a mock participant with annotated attributes."""
    p = MagicMock()
    p.id = pid or str(uuid4())
    p.name = name
    p.computed_score = computed_score
    p.solve_count = solve_count
    p.last_solve_time = last_solve_time
    p.team = team
    p.bracket = bracket
    return p


@pytest.fixture
def mock_participant_objects():
    """Patch CTFParticipant.objects for scoreboard tests."""
    with patch("ctf.services.scoring.CTFParticipant.objects") as mock_objects:
        yield mock_objects


class TestBracketScoring:
    """Tests for bracket-filtered scoreboards."""

    def test_get_scoreboard_with_bracket_filter(self, mock_participant_objects):
        """get_scoreboard filters by bracket_id when provided."""
        from ctf.services.scoring import get_scoreboard

        bracket_mock = MagicMock()
        bracket_mock.name = "Beginner"

        p1 = _make_participant("Alice", 200, 2, _NOW, bracket=bracket_mock)
        p2 = _make_participant("Bob", 100, 1, _NOW + timedelta(minutes=5), bracket=bracket_mock)

        qs_mock = MagicMock()
        qs_mock.annotate.return_value = qs_mock
        qs_mock.order_by.return_value = qs_mock
        qs_mock.select_related.return_value = qs_mock
        qs_mock.__iter__ = lambda self: iter([p1, p2])
        mock_participant_objects.filter.return_value = qs_mock

        event_id = uuid4()
        bracket_id = uuid4()
        result = get_scoreboard(event_id, bracket_id=bracket_id)

        # Verify bracket_id was passed to filter
        filter_kwargs = mock_participant_objects.filter.call_args[1]
        assert filter_kwargs["bracket_id"] == bracket_id

        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[0]["rank"] == 1
        assert result[1]["name"] == "Bob"
        assert result[1]["rank"] == 2

    def test_get_scoreboard_without_bracket_no_filter(self, mock_participant_objects):
        """get_scoreboard without bracket_id does not filter by bracket."""
        from ctf.services.scoring import get_scoreboard

        p1 = _make_participant("Alice", 200, 2, _NOW)

        qs_mock = MagicMock()
        qs_mock.annotate.return_value = qs_mock
        qs_mock.order_by.return_value = qs_mock
        qs_mock.select_related.return_value = qs_mock
        qs_mock.__iter__ = lambda self: iter([p1])
        mock_participant_objects.filter.return_value = qs_mock

        event_id = uuid4()
        result = get_scoreboard(event_id)

        # Verify bracket_id was NOT in filter kwargs
        filter_kwargs = mock_participant_objects.filter.call_args[1]
        assert "bracket_id" not in filter_kwargs
        assert len(result) == 1

    def test_scoreboard_includes_bracket_name(self, mock_participant_objects):
        """Scoreboard entries include bracket_name field."""
        from ctf.services.scoring import get_scoreboard

        bracket_mock = MagicMock()
        bracket_mock.name = "Advanced"

        p1 = _make_participant("Alice", 500, 5, _NOW, bracket=bracket_mock)

        qs_mock = MagicMock()
        qs_mock.annotate.return_value = qs_mock
        qs_mock.order_by.return_value = qs_mock
        qs_mock.select_related.return_value = qs_mock
        qs_mock.__iter__ = lambda self: iter([p1])
        mock_participant_objects.filter.return_value = qs_mock

        result = get_scoreboard(uuid4())
        assert result[0]["bracket_name"] == "Advanced"

    def test_scoreboard_bracket_name_none_when_no_bracket(self, mock_participant_objects):
        """bracket_name is None when participant has no bracket."""
        from ctf.services.scoring import get_scoreboard

        p1 = _make_participant("Alice", 500, 5, _NOW, bracket=None)

        qs_mock = MagicMock()
        qs_mock.annotate.return_value = qs_mock
        qs_mock.order_by.return_value = qs_mock
        qs_mock.select_related.return_value = qs_mock
        qs_mock.__iter__ = lambda self: iter([p1])
        mock_participant_objects.filter.return_value = qs_mock

        result = get_scoreboard(uuid4())
        assert result[0]["bracket_name"] is None


# ---------------------------------------------------------------------------
# View Tests
# ---------------------------------------------------------------------------


class TestBracketViews:
    """Tests for bracket-related views."""

    def test_admin_bracket_list(self, authenticated_organizer_client, ctf_event_with_brackets, brackets):
        """Admin bracket list shows all brackets."""
        response = authenticated_organizer_client.get(f"/ctf/admin/events/{ctf_event_with_brackets.pk}/brackets/")
        assert response.status_code == 200
        assert b"Beginner" in response.content
        assert b"Intermediate" in response.content
        assert b"Advanced" in response.content

    def test_admin_bracket_create(self, authenticated_organizer_client, ctf_event_with_brackets):
        """Admin can create a bracket via POST."""
        response = authenticated_organizer_client.post(
            f"/ctf/admin/events/{ctf_event_with_brackets.pk}/brackets/create/",
            {"name": "Expert", "description": "Top tier", "display_order": "3"},
        )
        assert response.status_code == 302
        assert CTFBracket.objects.filter(event=ctf_event_with_brackets, name="Expert").exists()

    def test_admin_bracket_edit(self, authenticated_organizer_client, brackets):
        """Admin can edit a bracket."""
        beginner, _, _ = brackets
        response = authenticated_organizer_client.post(
            f"/ctf/admin/brackets/{beginner.pk}/edit/",
            {"name": "Novice", "description": "Updated", "display_order": "0"},
        )
        assert response.status_code == 302
        beginner.refresh_from_db()
        assert beginner.name == "Novice"

    def test_admin_bracket_delete(self, authenticated_organizer_client, brackets):
        """Admin can delete a bracket via POST."""
        beginner, _, _ = brackets
        response = authenticated_organizer_client.post(f"/ctf/admin/brackets/{beginner.pk}/delete/")
        assert response.status_code == 302
        assert not CTFBracket.objects.filter(pk=beginner.pk).exists()

    def test_api_assign_bracket(
        self, authenticated_organizer_client, ctf_event_with_brackets, brackets, participant_user
    ):
        """API can assign a bracket to a participant."""
        import json

        beginner, _, _ = brackets
        participant = CTFParticipant.objects.create(
            event=ctf_event_with_brackets,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        response = authenticated_organizer_client.post(
            f"/ctf/api/participants/{participant.pk}/bracket/",
            json.dumps({"bracket_id": str(beginner.id)}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["bracket"]["name"] == "Beginner"

    def test_api_remove_bracket(
        self, authenticated_organizer_client, ctf_event_with_brackets, brackets, participant_user
    ):
        """API can remove a bracket assignment."""
        import json

        beginner, _, _ = brackets
        participant = CTFParticipant.objects.create(
            event=ctf_event_with_brackets,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
            bracket=beginner,
        )
        response = authenticated_organizer_client.post(
            f"/ctf/api/participants/{participant.pk}/bracket/",
            json.dumps({"bracket_id": None}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["bracket"] is None

    def test_scoreboard_with_bracket_param(self, authenticated_organizer_client, ctf_event_with_brackets, brackets):
        """Admin scoreboard accepts bracket query parameter."""
        beginner, _, _ = brackets
        response = authenticated_organizer_client.get(
            f"/ctf/admin/events/{ctf_event_with_brackets.pk}/scoreboard/?bracket={beginner.id}"
        )
        assert response.status_code == 200

    def test_api_scoreboard_includes_brackets(self, authenticated_organizer_client, ctf_event_with_brackets, brackets):
        """API scoreboard includes brackets list."""
        response = authenticated_organizer_client.get(f"/ctf/api/events/{ctf_event_with_brackets.pk}/scoreboard/")
        assert response.status_code == 200
        data = response.json()
        assert "brackets" in data
        assert len(data["brackets"]) == 3
        bracket_names = {b["name"] for b in data["brackets"]}
        assert bracket_names == {"Beginner", "Intermediate", "Advanced"}

    def test_api_scoreboard_with_bracket_filter(
        self, authenticated_organizer_client, ctf_event_with_brackets, brackets
    ):
        """API scoreboard returns bracket_rankings when bracket param set."""
        beginner, _, _ = brackets
        response = authenticated_organizer_client.get(
            f"/ctf/api/events/{ctf_event_with_brackets.pk}/scoreboard/?bracket={beginner.id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert "bracket_rankings" in data
        assert data["bracket_rankings"] is not None
