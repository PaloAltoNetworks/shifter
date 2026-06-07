"""Tests for CTF scoring service.

Unit tests covering all public functions in ctf/services/scoring.py
and scoring-related model edge cases. All ORM calls are mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ctf.services.scoring import (
    get_scoreboard,
    get_team_scoreboard,
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _make_participant(
    name: str,
    computed_score: int = 0,
    solve_count: int = 0,
    last_solve_time: datetime | None = None,
    team: MagicMock | None = None,
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
    return p


def _make_team(
    name: str,
    computed_score: int = 0,
    solve_count: int = 0,
    computed_member_count: int = 0,
    last_solve_time: datetime | None = None,
    tid: str | None = None,
) -> MagicMock:
    """Build a mock team with annotated attributes."""
    t = MagicMock()
    t.id = tid or str(uuid4())
    t.name = name
    t.computed_score = computed_score
    t.solve_count = solve_count
    t.computed_member_count = computed_member_count
    t.last_solve_time = last_solve_time
    return t


# -----------------------------------------------------------------------------
# Shared fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_submission_objects():
    """Patch CTFSubmission.objects for calculate_score tests."""
    with patch("ctf.services.scoring.CTFSubmission.objects") as mock_objects:
        yield mock_objects


@pytest.fixture
def mock_award_objects():
    """Patch CTFAward.objects for calculate_score and statistics tests."""
    with patch("ctf.services.scoring.CTFAward.objects") as mock_objects:
        yield mock_objects


@pytest.fixture
def mock_participant_objects():
    """Patch CTFParticipant.objects for scoreboard tests."""
    with patch("ctf.services.scoring.CTFParticipant.objects") as mock_objects:
        yield mock_objects


@pytest.fixture
def mock_team_objects():
    """Patch CTFTeam.objects for team scoreboard tests."""
    with patch("ctf.services.scoring.CTFTeam.objects") as mock_objects:
        yield mock_objects


# -----------------------------------------------------------------------------
# calculate_score tests
# -----------------------------------------------------------------------------


class TestGetScoreTimeline:
    """Tests for get_score_timeline().

    Verifies the chronological score progression (submissions + awards)
    with cumulative totals for a single participant.
    """

    @pytest.fixture
    def mock_models(self):
        """Patch all ORM objects used by get_score_timeline."""
        with (
            patch("ctf.services.scoring.CTFParticipant.objects") as mock_part,
            patch("ctf.services.scoring.CTFSubmission.objects") as mock_sub,
            patch("ctf.services.scoring.CTFAward.objects") as mock_award,
        ):
            yield mock_part, mock_sub, mock_award

    def _setup(self, mock_models, submissions=None, awards=None):
        """Configure mocks for a standard timeline query.

        Args:
            mock_models: Tuple of (participant, submission, award) mocks.
            submissions: List of (submitted_at, points_awarded, challenge_name) tuples.
            awards: List of (created_at, points, reason) tuples.

        Returns:
            UUID used as participant_id.
        """
        mock_part, mock_sub, mock_award = mock_models
        pid = uuid4()

        # Mock participant lookup
        participant = MagicMock()
        participant.event.event_start = _NOW - timedelta(hours=8)
        mock_part.select_related.return_value.get.return_value = participant

        # Mock submissions query chain
        sub_data = [
            {"submitted_at": s[0], "points_awarded": s[1], "challenge__name": s[2]} for s in (submissions or [])
        ]
        mock_sub.filter.return_value.values.return_value.order_by.return_value = sub_data

        # Mock awards query chain
        award_data = [{"created_at": a[0], "points": a[1], "reason": a[2]} for a in (awards or [])]
        mock_award.filter.return_value.values.return_value.order_by.return_value = award_data

        return pid

    def test_timeline_correct_submissions_ordered(self, mock_models):
        """Two solves produce correct cumulative sequence."""
        from ctf.services.scoring import get_score_timeline

        t1 = _NOW - timedelta(hours=6)
        t2 = _NOW - timedelta(hours=4)
        pid = self._setup(
            mock_models,
            submissions=[
                (t1, 100, "Web 101"),
                (t2, 200, "Crypto 201"),
            ],
        )

        timeline = get_score_timeline(pid)

        assert len(timeline) == 3  # origin + 2 solves
        assert timeline[0]["cumulative"] == 0
        assert timeline[0]["type"] == "start"
        assert timeline[1]["cumulative"] == 100
        assert timeline[1]["type"] == "solve"
        assert timeline[2]["cumulative"] == 300
        assert timeline[2]["type"] == "solve"

    def test_timeline_includes_awards(self, mock_models):
        """Solve + award are merged and sorted by timestamp."""
        from ctf.services.scoring import get_score_timeline

        t1 = _NOW - timedelta(hours=6)
        t2 = _NOW - timedelta(hours=5)
        pid = self._setup(
            mock_models,
            submissions=[(t1, 100, "Web 101")],
            awards=[(t2, 50, "Bonus for style")],
        )

        timeline = get_score_timeline(pid)

        assert len(timeline) == 3
        assert timeline[1]["type"] == "solve"
        assert timeline[1]["cumulative"] == 100
        assert timeline[2]["type"] == "award"
        assert timeline[2]["cumulative"] == 150

    def test_timeline_negative_award(self, mock_models):
        """Penalty (negative award) reduces cumulative score."""
        from ctf.services.scoring import get_score_timeline

        t1 = _NOW - timedelta(hours=6)
        t2 = _NOW - timedelta(hours=5)
        pid = self._setup(
            mock_models,
            submissions=[(t1, 200, "Pwn 301")],
            awards=[(t2, -50, "Penalty")],
        )

        timeline = get_score_timeline(pid)

        assert timeline[2]["cumulative"] == 150
        assert timeline[2]["points"] == -50

    def test_timeline_empty_activity(self, mock_models):
        """No submissions or awards returns only the origin point."""
        from ctf.services.scoring import get_score_timeline

        pid = self._setup(mock_models)

        timeline = get_score_timeline(pid)

        assert len(timeline) == 1
        assert timeline[0]["cumulative"] == 0
        assert timeline[0]["type"] == "start"

    def test_timeline_origin_at_event_start(self, mock_models):
        """First entry timestamp matches event_start."""
        from ctf.services.scoring import get_score_timeline

        pid = self._setup(mock_models)
        expected_start = (_NOW - timedelta(hours=8)).isoformat()

        timeline = get_score_timeline(pid)

        assert timeline[0]["timestamp"] == expected_start

    def test_timeline_excludes_incorrect_submissions(self, mock_models):
        """Only correct submissions appear — filter is in the query."""
        from ctf.services.scoring import get_score_timeline

        _mock_part, mock_sub, _mock_award = mock_models

        pid = self._setup(
            mock_models,
            submissions=[
                (_NOW - timedelta(hours=6), 100, "Web 101"),
            ],
        )

        get_score_timeline(pid)

        # Verify the filter was called with is_correct=True
        call_kwargs = mock_sub.filter.call_args[1]
        assert call_kwargs["is_correct"] is True

    def test_timeline_labels_truncated(self, mock_models):
        """Labels exceeding 50 characters are truncated."""
        from ctf.services.scoring import get_score_timeline

        long_name = "A" * 60
        pid = self._setup(
            mock_models,
            submissions=[
                (_NOW - timedelta(hours=6), 100, long_name),
            ],
        )

        timeline = get_score_timeline(pid)

        assert len(timeline[1]["label"]) == 50

    def test_timeline_type_field(self, mock_models):
        """Solve entries have type 'solve', award entries have type 'award'."""
        from ctf.services.scoring import get_score_timeline

        t1 = _NOW - timedelta(hours=6)
        t2 = _NOW - timedelta(hours=5)
        pid = self._setup(
            mock_models,
            submissions=[(t1, 100, "Web")],
            awards=[(t2, 25, "Bonus")],
        )

        timeline = get_score_timeline(pid)

        types = [e["type"] for e in timeline]
        assert types == ["start", "solve", "award"]

    def test_timeline_pre_start_awards_folded_into_origin(self, mock_models):
        """Awards granted before event_start are folded into the origin point."""
        from ctf.services.scoring import get_score_timeline

        # event_start is _NOW - 8h; award at _NOW - 10h is before start
        pre_start = _NOW - timedelta(hours=10)
        post_start = _NOW - timedelta(hours=6)
        pid = self._setup(
            mock_models,
            submissions=[(post_start, 100, "Web 101")],
            awards=[(pre_start, 50, "Early bonus")],
        )

        timeline = get_score_timeline(pid)

        # Origin includes the pre-start award
        assert timeline[0]["type"] == "start"
        assert timeline[0]["cumulative"] == 50
        assert timeline[0]["points"] == 50
        # Post-start solve adds on top
        assert timeline[1]["cumulative"] == 150
        # No entry for the pre-start award itself
        assert len(timeline) == 2


class TestScoreboardFreeze:
    """Tests for the freeze_at parameter on get_scoreboard / get_team_scoreboard.

    Each "with freeze_at" test pins the chained ``CTFSubmission.objects.filter(...).filter(submitted_at__lt=…)``
    / ``CTFAward.objects.filter(...).filter(created_at__lt=…)`` calls so a refactor
    that silently drops the freeze cutoff would fail here. The bare-call tests
    pin the converse: when ``freeze_at`` is ``None``, no ``submitted_at__lt`` /
    ``created_at__lt`` kwarg appears on the chained filter.
    """

    @staticmethod
    def _collect_filter_kwargs(mock_objects: MagicMock) -> list[dict]:
        """Return every kwargs dict from every `.filter(...)` call anywhere in
        the chain starting at `mock_objects.filter`. The team scoreboard chains
        `.filter(...).filter(eligible_q).filter(submitted_at__lt=...)` so the
        freeze-at kwarg lives at the third level; the participant scoreboard
        chains only twice. Walking the chain (rather than hardcoding a depth)
        keeps the assertion stable under future refactors that insert another
        chain link. MagicMock auto-creates child mocks on every attribute
        access, so we bound the walk with a depth cap.
        """
        collected: list[dict] = []
        node = mock_objects.filter
        # 8 levels is well above any real ORM chain (participant scoreboard
        # uses 2, team scoreboard uses 3 with bracket_id).
        for _ in range(8):
            collected.extend(call.kwargs for call in node.call_args_list)
            node = node.return_value.filter
        return collected

    def _has_filter_kwarg(self, mock_objects: MagicMock, kwarg: str, value) -> bool:
        return any(call.get(kwarg) == value for call in self._collect_filter_kwargs(mock_objects))

    def _filter_kwarg_present(self, mock_objects: MagicMock, kwarg: str) -> bool:
        return any(kwarg in call for call in self._collect_filter_kwargs(mock_objects))

    def test_get_scoreboard_accepts_freeze_at(
        self,
        mock_participant_objects,
        mock_queryset,
        mock_submission_objects,
        mock_award_objects,
    ):
        """get_scoreboard with freeze_at chains submitted_at__lt / created_at__lt onto the inner querysets."""
        freeze_time = _NOW - timedelta(hours=1)
        p_alice = _make_participant("Alice", computed_score=100, solve_count=1, last_solve_time=_NOW)
        mock_participant_objects.filter.return_value = mock_queryset
        mock_queryset.__iter__ = MagicMock(return_value=iter([p_alice]))

        result = get_scoreboard(uuid4(), freeze_at=freeze_time)

        assert len(result) == 1
        assert result[0]["name"] == "Alice"
        assert self._has_filter_kwarg(mock_submission_objects, "submitted_at__lt", freeze_time)
        assert self._has_filter_kwarg(mock_award_objects, "created_at__lt", freeze_time)

    def test_get_scoreboard_without_freeze_at(
        self,
        mock_participant_objects,
        mock_queryset,
        mock_submission_objects,
        mock_award_objects,
    ):
        """get_scoreboard with freeze_at=None does NOT chain a freeze filter."""
        p_alice = _make_participant("Alice", computed_score=100, solve_count=1)
        mock_participant_objects.filter.return_value = mock_queryset
        mock_queryset.__iter__ = MagicMock(return_value=iter([p_alice]))

        result = get_scoreboard(uuid4(), freeze_at=None)

        assert len(result) == 1
        assert not self._filter_kwarg_present(mock_submission_objects, "submitted_at__lt")
        assert not self._filter_kwarg_present(mock_award_objects, "created_at__lt")

    def test_get_team_scoreboard_accepts_freeze_at(
        self,
        mock_team_objects,
        mock_queryset,
        mock_submission_objects,
        mock_award_objects,
    ):
        """get_team_scoreboard with freeze_at chains submitted_at__lt / created_at__lt onto the inner querysets."""
        freeze_time = _NOW - timedelta(hours=1)
        t_alpha = _make_team("Alpha", computed_score=200, solve_count=2, computed_member_count=3)
        mock_team_objects.filter.return_value = mock_queryset
        mock_queryset.__iter__ = MagicMock(return_value=iter([t_alpha]))

        result = get_team_scoreboard(uuid4(), freeze_at=freeze_time)

        assert len(result) == 1
        assert result[0]["name"] == "Alpha"
        assert self._has_filter_kwarg(mock_submission_objects, "submitted_at__lt", freeze_time)
        assert self._has_filter_kwarg(mock_award_objects, "created_at__lt", freeze_time)

    def test_get_team_scoreboard_without_freeze_at(
        self,
        mock_team_objects,
        mock_queryset,
        mock_submission_objects,
        mock_award_objects,
    ):
        """get_team_scoreboard with freeze_at=None does NOT chain a freeze filter."""
        t_alpha = _make_team("Alpha", computed_score=200, solve_count=2, computed_member_count=3)
        mock_team_objects.filter.return_value = mock_queryset
        mock_queryset.__iter__ = MagicMock(return_value=iter([t_alpha]))

        result = get_team_scoreboard(uuid4(), freeze_at=None)

        assert len(result) == 1
        assert not self._filter_kwarg_present(mock_submission_objects, "submitted_at__lt")
        assert not self._filter_kwarg_present(mock_award_objects, "created_at__lt")


class TestIsScoreboardFrozen:
    """Tests for CTFEvent.is_scoreboard_frozen property."""

    def _make_event(self, freeze_at=None, status="active"):
        """Create a mock event with freeze configuration."""
        from ctf.models import CTFEvent

        event = MagicMock(spec=CTFEvent)
        event.scoreboard_freeze_at = freeze_at
        event.status = status
        event.is_scoreboard_frozen = CTFEvent.is_scoreboard_frozen.fget(event)
        return event

    def test_frozen_when_past_freeze_time_and_active(self):
        """Event is frozen when now >= freeze_at and status is active."""
        event = self._make_event(
            freeze_at=_NOW - timedelta(hours=1),
            status="active",
        )
        assert event.is_scoreboard_frozen is True

    def test_not_frozen_when_no_freeze_time(self):
        """Event is not frozen when scoreboard_freeze_at is None."""
        event = self._make_event(freeze_at=None, status="active")
        assert event.is_scoreboard_frozen is False

    def test_not_frozen_when_event_ended(self):
        """Event is not frozen when status is ended (freeze lifts on end)."""
        event = self._make_event(
            freeze_at=_NOW - timedelta(hours=1),
            status="ended",
        )
        assert event.is_scoreboard_frozen is False

    @patch("ctf.models.event.timezone")
    def test_not_frozen_before_freeze_time(self, mock_tz):
        """Event is not frozen when freeze_at is in the future."""
        mock_tz.now.return_value = _NOW
        event = self._make_event(
            freeze_at=_NOW + timedelta(hours=24),
            status="active",
        )
        assert event.is_scoreboard_frozen is False


class TestScoreboardVisibility:
    """Tests for CTFEvent.scoreboard_visible field behaviour."""

    def _make_event(self, scoreboard_visible=True):
        """Create a mock event with visibility configuration."""
        from ctf.models import CTFEvent

        event = MagicMock(spec=CTFEvent)
        event.scoreboard_visible = scoreboard_visible
        return event

    def test_scoreboard_visible_by_default(self):
        """scoreboard_visible defaults to True."""
        from ctf.models import CTFEvent

        field = CTFEvent._meta.get_field("scoreboard_visible")
        assert field.default is True

    def test_scoreboard_hidden_when_not_visible(self):
        """Event with scoreboard_visible=False reports hidden."""
        event = self._make_event(scoreboard_visible=False)
        assert event.scoreboard_visible is False

    def test_scoreboard_shown_when_visible(self):
        """Event with scoreboard_visible=True reports visible."""
        event = self._make_event(scoreboard_visible=True)
        assert event.scoreboard_visible is True

    def test_scoreboard_visible_in_mutable_fields(self):
        """scoreboard_visible is in the event mutable fields whitelist."""
        from ctf.services.event import _EVENT_MUTABLE_FIELDS

        assert "scoreboard_visible" in _EVENT_MUTABLE_FIELDS
