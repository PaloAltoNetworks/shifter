"""Tests for CTF scoring service.

Unit tests covering all public functions in ctf/services/scoring.py
and scoring-related model edge cases. All ORM calls are mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ctf.services.scoring import (
    get_event_statistics,
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


class TestGetEventStatistics:
    """Tests for get_event_statistics()."""

    @pytest.fixture
    def mock_event_models(self):
        """Patch all model managers and get_scoreboard used by get_event_statistics."""
        with (
            patch("ctf.models.CTFEvent.objects") as mock_event,
            patch("ctf.services.scoring.CTFParticipant.objects") as mock_part,
            patch("ctf.models.CTFChallenge.objects") as mock_chal,
            patch("ctf.services.scoring.CTFSubmission.objects") as mock_sub,
            patch("ctf.services.scoring.CTFAward.objects") as mock_award,
            patch("ctf.services.scoring.get_scoreboard") as mock_scoreboard,
        ):
            yield mock_event, mock_part, mock_chal, mock_sub, mock_award, mock_scoreboard

    def _setup_mocks(
        self,
        mock_event_models,
        *,
        participant_count=3,
        active_count=2,
        challenge_count=3,
        total_subs=5,
        correct_subs=2,
        points_awarded=200,
        award_count=0,
        solved_challenge_count=2,
        scoreboard_scores=None,
        duration_hours=4.0,
    ):
        """Helper to configure mocks for get_event_statistics tests."""
        mock_event, mock_part, mock_chal, mock_sub, mock_award, mock_scoreboard = mock_event_models

        event_obj = MagicMock()
        event_obj.duration_hours = duration_hours
        mock_event.get.return_value = event_obj

        # Participants
        part_qs = MagicMock()
        mock_part.filter.return_value = part_qs
        part_qs.count.return_value = participant_count
        active_qs = MagicMock()
        active_qs.count.return_value = active_count
        part_qs.filter.return_value = active_qs
        active_qs.distinct.return_value = active_qs

        # Challenges
        chal_qs = MagicMock()
        mock_chal.filter.return_value = chal_qs
        chal_qs.count.return_value = challenge_count

        # Submissions
        sub_qs = MagicMock()
        mock_sub.filter.return_value = sub_qs
        sub_qs.count.return_value = total_subs
        correct_qs = MagicMock()
        sub_qs.filter.return_value = correct_qs
        correct_qs.count.return_value = correct_subs
        correct_qs.aggregate.return_value = {"total": points_awarded}
        # For challenges_with_zero_solves: correct_qs.values().distinct().count()
        values_qs = MagicMock()
        correct_qs.values.return_value = values_qs
        distinct_qs = MagicMock()
        values_qs.distinct.return_value = distinct_qs
        distinct_qs.count.return_value = solved_challenge_count

        # Awards
        award_qs = MagicMock()
        mock_award.filter.return_value = award_qs
        award_qs.count.return_value = award_count

        # Scoreboard
        if scoreboard_scores is None:
            scoreboard_scores = [100, 50, 50]
        mock_scoreboard.return_value = [{"score": s} for s in scoreboard_scores]

        return event_obj

    def test_basic_event_stats(self, mock_event_models):
        """Returns correct participant count, challenge count, submissions."""
        eid = uuid4()
        self._setup_mocks(
            mock_event_models,
            participant_count=3,
            active_count=2,
            challenge_count=3,
            total_subs=5,
            correct_subs=2,
            points_awarded=200,
            solved_challenge_count=2,
            scoreboard_scores=[100, 50, 50],
            duration_hours=4.0,
        )

        stats = get_event_statistics(eid)

        assert stats["event_id"] == str(eid)
        assert stats["participant_count"] == 3
        assert stats["active_participants"] == 2
        assert stats["challenge_count"] == 3
        assert stats["challenges_with_zero_solves"] == 1
        assert stats["total_submissions"] == 5
        assert stats["correct_submissions"] == 2
        assert stats["incorrect_submissions"] == 3
        assert stats["average_score"] == 66.7
        assert stats["median_score"] == 50
        assert stats["event_duration_hours"] == 4.0
        assert stats["total_points_awarded"] == 200
        assert stats["total_awards"] == 0

    def test_nonexistent_event(self):
        """Non-existent event returns empty dict."""
        from ctf.models import CTFEvent

        with patch("ctf.models.CTFEvent.objects") as mock_event:
            mock_event.get.side_effect = CTFEvent.DoesNotExist
            assert get_event_statistics(uuid4()) == {}

    def test_event_with_no_activity(self, mock_event_models):
        """Event with no participants/submissions returns zero counts."""
        eid = uuid4()
        self._setup_mocks(
            mock_event_models,
            participant_count=0,
            active_count=0,
            challenge_count=0,
            total_subs=0,
            correct_subs=0,
            points_awarded=0,
            solved_challenge_count=0,
            scoreboard_scores=[],
            duration_hours=2.0,
        )

        stats = get_event_statistics(eid)

        assert stats["participant_count"] == 0
        assert stats["active_participants"] == 0
        assert stats["challenge_count"] == 0
        assert stats["challenges_with_zero_solves"] == 0
        assert stats["total_submissions"] == 0
        assert stats["correct_submissions"] == 0
        assert stats["incorrect_submissions"] == 0
        assert stats["average_score"] == 0
        assert stats["median_score"] == 0
        assert stats["event_duration_hours"] == 2.0
        assert stats["total_points_awarded"] == 0
        assert stats["total_awards"] == 0

    def test_all_challenges_solved(self, mock_event_models):
        """All challenges have at least one solve."""
        eid = uuid4()
        self._setup_mocks(
            mock_event_models,
            challenge_count=5,
            solved_challenge_count=5,
            scoreboard_scores=[100, 80, 60],
        )

        stats = get_event_statistics(eid)
        assert stats["challenges_with_zero_solves"] == 0

    def test_single_participant_score(self, mock_event_models):
        """Average and median are equal with a single participant."""
        eid = uuid4()
        self._setup_mocks(
            mock_event_models,
            participant_count=1,
            active_count=1,
            scoreboard_scores=[75],
        )

        stats = get_event_statistics(eid)
        assert stats["average_score"] == 75
        assert stats["median_score"] == 75

    def test_even_number_of_scores(self, mock_event_models):
        """Median with even number of participants uses midpoint."""
        eid = uuid4()
        self._setup_mocks(
            mock_event_models,
            scoreboard_scores=[100, 80, 60, 40],
        )

        stats = get_event_statistics(eid)
        assert stats["average_score"] == 70.0
        assert stats["median_score"] == 70.0


class TestCalculatePointsWithPenalty:
    """Tests for CTFChallenge.calculate_points_with_penalty().

    This is a pure model method that only reads self.points —
    no DB calls needed, just mock instances.
    """

    def _make_challenge(self, points):
        """Create a mock challenge with the fields needed by calculate_points_with_penalty."""
        from ctf.models import CTFChallenge

        challenge = MagicMock(spec=CTFChallenge)
        challenge.points = points
        challenge.calculate_points_with_penalty = CTFChallenge.calculate_points_with_penalty.__get__(challenge)
        return challenge

    def test_zero_penalty_returns_full_points(self):
        """0% cumulative penalty gives full points."""
        challenge = self._make_challenge(points=100)
        assert challenge.calculate_points_with_penalty(0) == 100

    def test_100_percent_penalty_floors_at_zero(self):
        """100% cumulative penalty awards 0 points (CTF-203 floor)."""
        challenge = self._make_challenge(points=100)
        assert challenge.calculate_points_with_penalty(100) == 0

    def test_partial_penalty_reduces_correctly(self):
        """25% penalty on 200 points = 150 points."""
        challenge = self._make_challenge(points=200)
        assert challenge.calculate_points_with_penalty(25) == 150

    def test_over_100_capped_floors_at_zero(self):
        """Penalties over 100% are capped at the floor (0), not historical 1."""
        challenge = self._make_challenge(points=100)
        assert challenge.calculate_points_with_penalty(150) == 0
