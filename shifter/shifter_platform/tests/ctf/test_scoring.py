"""Tests for CTF scoring service.

Unit tests covering all public functions in ctf/services/scoring.py
and scoring-related model edge cases. All ORM calls are mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ctf.enums import ParticipantStatus
from ctf.services.scoring import (
    calculate_score,
    get_challenge_statistics,
    get_event_statistics,
    get_participant_rank,
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


class TestCalculateScore:
    """Tests for calculate_score()."""

    def test_score_sums_correct_submissions_only(self, mock_submission_objects, mock_award_objects):
        """Correct submissions are summed; incorrect ones are ignored."""
        pid = uuid4()
        mock_qs = MagicMock()
        mock_submission_objects.filter.return_value = mock_qs
        mock_qs.aggregate.return_value = {"total": 300}

        award_qs = MagicMock()
        mock_award_objects.filter.return_value = award_qs
        award_qs.aggregate.return_value = {"total": 0}

        assert calculate_score(pid) == 300
        mock_submission_objects.filter.assert_called_once_with(participant_id=pid, is_correct=True)

    def test_score_zero_with_no_submissions(self, mock_submission_objects, mock_award_objects):
        """Participant with no submissions scores 0."""
        pid = uuid4()
        mock_qs = MagicMock()
        mock_submission_objects.filter.return_value = mock_qs
        mock_qs.aggregate.return_value = {"total": 0}

        award_qs = MagicMock()
        mock_award_objects.filter.return_value = award_qs
        award_qs.aggregate.return_value = {"total": 0}

        assert calculate_score(pid) == 0

    def test_score_zero_with_only_incorrect(self, mock_submission_objects, mock_award_objects):
        """Participant with only incorrect submissions scores 0 (Coalesce returns 0)."""
        pid = uuid4()
        mock_qs = MagicMock()
        mock_submission_objects.filter.return_value = mock_qs
        mock_qs.aggregate.return_value = {"total": 0}

        award_qs = MagicMock()
        mock_award_objects.filter.return_value = award_qs
        award_qs.aggregate.return_value = {"total": 0}

        assert calculate_score(pid) == 0


# -----------------------------------------------------------------------------
# get_scoreboard tests
# -----------------------------------------------------------------------------


class TestGetScoreboard:
    """Tests for get_scoreboard()."""

    @staticmethod
    def _wire_qs(mock_participant_objects, mock_queryset, participants):
        """Wire a shared mock_queryset to the participant manager and make it iterable."""
        mock_participant_objects.filter.return_value = mock_queryset
        mock_queryset.__iter__ = MagicMock(return_value=iter(participants))
        return mock_queryset

    def test_ranked_by_score_descending(self, mock_participant_objects, mock_queryset):
        """Higher score = lower rank number."""
        p_bob = _make_participant("Bob", computed_score=300, solve_count=2, last_solve_time=_NOW)
        p_charlie = _make_participant("Charlie", computed_score=200, solve_count=1, last_solve_time=_NOW)
        p_alice = _make_participant("Alice", computed_score=100, solve_count=1, last_solve_time=_NOW)

        self._wire_qs(mock_participant_objects, mock_queryset, [p_bob, p_charlie, p_alice])

        board = get_scoreboard(uuid4())

        assert board[0]["name"] == "Bob"
        assert board[0]["score"] == 300
        assert board[0]["rank"] == 1

        assert board[1]["name"] == "Charlie"
        assert board[1]["score"] == 200
        assert board[1]["rank"] == 2

        assert board[2]["name"] == "Alice"
        assert board[2]["score"] == 100
        assert board[2]["rank"] == 3

    def test_tie_breaking_by_earlier_last_solve(self, mock_participant_objects, mock_queryset):
        """Same score: participant who solved last challenge earlier ranks higher."""
        early = _NOW - timedelta(minutes=10)
        late = _NOW

        p_alice = _make_participant("Alice", computed_score=100, solve_count=1, last_solve_time=early)
        p_bob = _make_participant("Bob", computed_score=100, solve_count=1, last_solve_time=late)

        self._wire_qs(mock_participant_objects, mock_queryset, [p_alice, p_bob])

        board = get_scoreboard(uuid4())

        tied = [e for e in board if e["score"] == 100]
        assert tied[0]["name"] == "Alice"
        assert tied[1]["name"] == "Bob"
        assert tied[0]["rank"] == 1
        assert tied[1]["rank"] == 2

    def test_limit_parameter(self, mock_participant_objects, mock_queryset):
        """Limit restricts the number of scoreboard entries."""
        p1 = _make_participant("Charlie", computed_score=300, solve_count=1, last_solve_time=_NOW)
        p2 = _make_participant("Bob", computed_score=200, solve_count=1, last_solve_time=_NOW)

        mock_participant_objects.filter.return_value = mock_queryset

        # Slicing via __getitem__ returns a new qs that yields limited results
        sliced_qs = MagicMock()
        sliced_qs.__iter__ = MagicMock(return_value=iter([p1, p2]))
        mock_queryset.__getitem__ = MagicMock(return_value=sliced_qs)

        board = get_scoreboard(uuid4(), limit=2)
        assert len(board) == 2
        assert board[0]["score"] == 300

    def test_excludes_non_active_statuses(self, mock_participant_objects, mock_queryset):
        """Only ACTIVE, REGISTERED, and COMPLETED participants appear.

        The service passes status__in filter. We verify the filter is called
        with the right statuses, and that the returned list only has what the
        queryset yields (which excludes disqualified).
        """
        p_active = _make_participant("Active", computed_score=100, solve_count=1, last_solve_time=_NOW)

        self._wire_qs(mock_participant_objects, mock_queryset, [p_active])

        board = get_scoreboard(uuid4())
        names = [e["name"] for e in board]
        assert "Active" in names

        # Verify filter was called with the correct status values
        call_kwargs = mock_participant_objects.filter.call_args[1]
        assert set(call_kwargs["status__in"]) == {
            ParticipantStatus.ACTIVE.value,
            ParticipantStatus.REGISTERED.value,
            ParticipantStatus.COMPLETED.value,
        }

    def test_empty_scoreboard(self, mock_participant_objects, mock_queryset):
        """Event with no participants returns empty list."""
        self._wire_qs(mock_participant_objects, mock_queryset, [])

        board = get_scoreboard(uuid4())
        assert board == []

    def test_scoreboard_includes_solve_count(self, mock_participant_objects, mock_queryset):
        """solve_count reflects number of correct submissions."""
        p_alice = _make_participant("Alice", computed_score=300, solve_count=2, last_solve_time=_NOW)

        self._wire_qs(mock_participant_objects, mock_queryset, [p_alice])

        board = get_scoreboard(uuid4())
        p1_entry = next(e for e in board if e["name"] == "Alice")
        assert p1_entry["solve_count"] == 2


# -----------------------------------------------------------------------------
# get_team_scoreboard tests
# -----------------------------------------------------------------------------


class TestGetTeamScoreboard:
    """Tests for get_team_scoreboard()."""

    @staticmethod
    def _wire_qs(mock_team_objects, mock_queryset, teams):
        """Wire a shared mock_queryset to the team manager and make it iterable."""
        mock_team_objects.filter.return_value = mock_queryset
        mock_queryset.__iter__ = MagicMock(return_value=iter(teams))
        return mock_queryset

    def test_team_scores_aggregated(self, mock_team_objects, mock_queryset):
        """Team score is the sum of all members' correct submissions."""
        t_alpha = _make_team("Alpha", computed_score=200, solve_count=2, computed_member_count=2, last_solve_time=_NOW)
        t_bravo = _make_team("Bravo", computed_score=100, solve_count=1, computed_member_count=1, last_solve_time=_NOW)

        self._wire_qs(mock_team_objects, mock_queryset, [t_alpha, t_bravo])

        board = get_team_scoreboard(uuid4())

        assert board[0]["name"] == "Alpha"
        assert board[0]["score"] == 200
        assert board[0]["rank"] == 1
        assert board[0]["member_count"] == 2

        assert board[1]["name"] == "Bravo"
        assert board[1]["score"] == 100
        assert board[1]["rank"] == 2

    def test_team_scoreboard_limit(self, mock_team_objects, mock_queryset):
        """Limit restricts team scoreboard results."""
        t_alpha = _make_team("Alpha", computed_score=200, solve_count=1, computed_member_count=2, last_solve_time=_NOW)

        mock_team_objects.filter.return_value = mock_queryset

        sliced_qs = MagicMock()
        sliced_qs.__iter__ = MagicMock(return_value=iter([t_alpha]))
        mock_queryset.__getitem__ = MagicMock(return_value=sliced_qs)

        board = get_team_scoreboard(uuid4(), limit=1)
        assert len(board) == 1

    def test_team_with_no_solves_scores_zero(self, mock_team_objects, mock_queryset):
        """Teams with no correct submissions have score 0."""
        t_alpha = _make_team("Alpha", computed_score=0, computed_member_count=2)
        t_bravo = _make_team("Bravo", computed_score=0, computed_member_count=1)

        self._wire_qs(mock_team_objects, mock_queryset, [t_alpha, t_bravo])

        board = get_team_scoreboard(uuid4())
        for entry in board:
            assert entry["score"] == 0

    def test_team_solve_count_is_unique_challenges(self, mock_team_objects, mock_queryset):
        """solve_count should reflect unique challenges solved, not total submissions."""
        # Mock team where 3 members solved 2 unique challenges (some overlap)
        t_alpha = _make_team(
            "Alpha",
            computed_score=300,
            solve_count=2,  # 2 unique challenges
            computed_member_count=3,
            last_solve_time=_NOW,
        )

        self._wire_qs(mock_team_objects, mock_queryset, [t_alpha])

        board = get_team_scoreboard(uuid4())
        assert board[0]["solve_count"] == 2


# -----------------------------------------------------------------------------
# get_participant_rank tests
# -----------------------------------------------------------------------------


class TestGetParticipantRank:
    """Tests for get_participant_rank()."""

    def test_returns_correct_rank(self, mock_participant_objects):
        """Rank matches scoreboard position."""
        pid1 = str(uuid4())
        pid2 = str(uuid4())
        pid3 = str(uuid4())

        # Mock participant lookup
        mock_participant = MagicMock()
        mock_participant.event_id = uuid4()
        mock_participant_objects.get.return_value = mock_participant

        # Mock the scoreboard queryset chain (called inside get_scoreboard)
        p1 = _make_participant("Charlie", computed_score=300, solve_count=1, last_solve_time=_NOW, pid=pid3)
        p2 = _make_participant("Bob", computed_score=200, solve_count=1, last_solve_time=_NOW, pid=pid2)
        p3 = _make_participant("Alice", computed_score=100, solve_count=1, last_solve_time=_NOW, pid=pid1)

        qs = MagicMock()
        mock_participant_objects.filter.return_value = qs
        qs.annotate.return_value = qs
        qs.order_by.return_value = qs
        qs.select_related.return_value = qs
        qs.__iter__ = MagicMock(return_value=iter([p1, p2, p3]))

        assert get_participant_rank(pid3) == 1

        # Reset iterator for next call
        qs.__iter__ = MagicMock(return_value=iter([p1, p2, p3]))
        assert get_participant_rank(pid2) == 2

        qs.__iter__ = MagicMock(return_value=iter([p1, p2, p3]))
        assert get_participant_rank(pid1) == 3

    def test_returns_none_for_nonexistent_participant(self, mock_participant_objects):
        """Non-existent participant ID returns None."""
        from ctf.models import CTFParticipant

        mock_participant_objects.get.side_effect = CTFParticipant.DoesNotExist

        assert get_participant_rank(uuid4()) is None

    def test_participant_with_no_submissions_has_rank(self, mock_participant_objects):
        """Participants with no submissions still appear on scoreboard (rank by 0 score)."""
        pid1 = str(uuid4())
        pid2 = str(uuid4())

        mock_participant = MagicMock()
        mock_participant.event_id = uuid4()
        mock_participant_objects.get.return_value = mock_participant

        p1 = _make_participant("Alice", computed_score=100, solve_count=1, last_solve_time=_NOW, pid=pid1)
        p2 = _make_participant("Bob", computed_score=0, solve_count=0, last_solve_time=None, pid=pid2)

        qs = MagicMock()
        mock_participant_objects.filter.return_value = qs
        qs.annotate.return_value = qs
        qs.order_by.return_value = qs
        qs.select_related.return_value = qs
        qs.__iter__ = MagicMock(return_value=iter([p1, p2]))

        rank = get_participant_rank(pid1)
        assert rank == 1

        # p2 with 0 score still has a rank
        qs.__iter__ = MagicMock(return_value=iter([p1, p2]))
        rank_p2 = get_participant_rank(pid2)
        assert rank_p2 is not None


# -----------------------------------------------------------------------------
# get_challenge_statistics tests
# -----------------------------------------------------------------------------


class TestGetChallengeStatistics:
    """Tests for get_challenge_statistics()."""

    @pytest.fixture
    def mock_challenge_and_submissions(self):
        """Patch CTFChallenge.objects and CTFSubmission.objects for stats tests.

        CTFChallenge is imported locally inside get_challenge_statistics,
        so we patch it at ctf.models rather than ctf.services.scoring.
        """
        with (
            patch("ctf.services.scoring.CTFSubmission.objects") as mock_sub,
            patch("ctf.models.CTFChallenge.objects") as mock_chal,
        ):
            yield mock_chal, mock_sub

    def test_basic_statistics(self, mock_challenge_and_submissions):
        """Returns correct solve count, attempts, and first blood."""
        mock_chal, mock_sub = mock_challenge_and_submissions
        cid = uuid4()

        mock_challenge = MagicMock()
        mock_chal.get.return_value = mock_challenge

        # All submissions queryset
        all_qs = MagicMock()
        mock_sub.filter.return_value = all_qs
        all_qs.count.return_value = 4

        # Correct submissions queryset
        correct_qs = MagicMock()
        all_qs.filter.return_value = correct_qs
        correct_qs.count.return_value = 2

        # First blood
        first_blood_sub = MagicMock()
        first_blood_sub.participant.name = "Alice"
        first_blood_sub.submitted_at.isoformat.return_value = "2026-01-15T12:00:00+00:00"
        ordered_qs = MagicMock()
        correct_qs.order_by.return_value = ordered_qs
        ordered_qs.first.return_value = first_blood_sub

        # Distinct participants
        values_qs = MagicMock()
        all_qs.values.return_value = values_qs
        distinct_qs = MagicMock()
        values_qs.distinct.return_value = distinct_qs
        distinct_qs.count.return_value = 3

        stats = get_challenge_statistics(cid)

        assert stats["challenge_id"] == str(cid)
        assert stats["total_attempts"] == 4
        assert stats["solve_count"] == 2
        assert stats["first_blood"] is not None
        assert stats["first_blood"]["participant_name"] == "Alice"

    def test_no_submissions(self, mock_challenge_and_submissions):
        """Challenge with no submissions returns zero counts."""
        mock_chal, mock_sub = mock_challenge_and_submissions
        cid = uuid4()

        mock_chal.get.return_value = MagicMock()

        all_qs = MagicMock()
        mock_sub.filter.return_value = all_qs
        all_qs.count.return_value = 0

        correct_qs = MagicMock()
        all_qs.filter.return_value = correct_qs
        correct_qs.count.return_value = 0
        ordered_qs = MagicMock()
        correct_qs.order_by.return_value = ordered_qs
        ordered_qs.first.return_value = None

        values_qs = MagicMock()
        all_qs.values.return_value = values_qs
        distinct_qs = MagicMock()
        values_qs.distinct.return_value = distinct_qs
        distinct_qs.count.return_value = 0

        stats = get_challenge_statistics(cid)

        assert stats["total_attempts"] == 0
        assert stats["solve_count"] == 0
        assert stats["first_blood"] is None
        assert stats["solve_rate"] == 0

    def test_nonexistent_challenge(self):
        """Non-existent challenge returns empty dict."""
        from ctf.models import CTFChallenge

        with patch("ctf.models.CTFChallenge.objects") as mock_chal:
            mock_chal.get.side_effect = CTFChallenge.DoesNotExist
            assert get_challenge_statistics(uuid4()) == {}

    def test_solve_rate(self, mock_challenge_and_submissions):
        """Solve rate = solvers / distinct participants who attempted."""
        mock_chal, mock_sub = mock_challenge_and_submissions
        cid = uuid4()

        mock_chal.get.return_value = MagicMock()

        all_qs = MagicMock()
        mock_sub.filter.return_value = all_qs
        all_qs.count.return_value = 2

        correct_qs = MagicMock()
        all_qs.filter.return_value = correct_qs
        correct_qs.count.return_value = 1
        ordered_qs = MagicMock()
        correct_qs.order_by.return_value = ordered_qs
        ordered_qs.first.return_value = None  # Not testing first blood here

        values_qs = MagicMock()
        all_qs.values.return_value = values_qs
        distinct_qs = MagicMock()
        values_qs.distinct.return_value = distinct_qs
        distinct_qs.count.return_value = 2

        stats = get_challenge_statistics(cid)
        # 1 solver out of 2 participants who attempted
        assert stats["solve_rate"] == pytest.approx(0.5)


# -----------------------------------------------------------------------------
# get_event_statistics tests
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


# -----------------------------------------------------------------------------
# calculate_points_with_penalty edge cases (model method)
# -----------------------------------------------------------------------------


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

    def test_100_percent_penalty_guarantees_minimum_1_point(self):
        """100% penalty still awards at least 1 point."""
        challenge = self._make_challenge(points=100)
        assert challenge.calculate_points_with_penalty(100) == 1

    def test_partial_penalty_reduces_correctly(self):
        """25% penalty on 200 points = 150 points."""
        challenge = self._make_challenge(points=200)
        assert challenge.calculate_points_with_penalty(25) == 150

    def test_over_100_capped(self):
        """Penalties over 100% are capped — still awards 1 point."""
        challenge = self._make_challenge(points=100)
        assert challenge.calculate_points_with_penalty(150) == 1


# -----------------------------------------------------------------------------
# get_score_timeline
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
