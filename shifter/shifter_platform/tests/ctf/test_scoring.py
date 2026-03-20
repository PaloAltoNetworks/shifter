"""Tests for CTF scoring service.

Integration-style tests covering all public functions in ctf/services/scoring.py
and scoring-related model edge cases.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ctf.enums import (
    ChallengeCategory,
    ChallengeDifficulty,
    EventStatus,
    ParticipantStatus,
)
from ctf.models import (
    CTFChallenge,
    CTFEvent,
    CTFParticipant,
    CTFSubmission,
    CTFTeam,
)
from ctf.services.scoring import (
    calculate_score,
    get_challenge_statistics,
    get_event_statistics,
    get_participant_rank,
    get_scoreboard,
    get_team_scoreboard,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def active_event(organizer_user):
    """Create an active event for scoring tests."""
    return CTFEvent.objects.create(
        name="Scoring Test Event",
        description="Event for scoring tests",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
    )


@pytest.fixture
def challenges(active_event):
    """Create three challenges with different point values."""
    c1 = CTFChallenge.objects.create(
        event=active_event,
        name="Easy Web",
        description="Easy web challenge",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$hash1",
    )
    c2 = CTFChallenge.objects.create(
        event=active_event,
        name="Medium Crypto",
        description="Medium crypto challenge",
        category=ChallengeCategory.CRYPTO.value,
        points=200,
        difficulty=ChallengeDifficulty.MEDIUM.value,
        flag_hash="$2b$12$hash2",
    )
    c3 = CTFChallenge.objects.create(
        event=active_event,
        name="Hard Pwn",
        description="Hard pwn challenge",
        category=ChallengeCategory.PWN.value,
        points=300,
        difficulty=ChallengeDifficulty.HARD.value,
        flag_hash="$2b$12$hash3",
    )
    return c1, c2, c3


@pytest.fixture
def three_participants(active_event, participant_user, second_participant_user):
    """Create three active participants for the event."""
    p1 = CTFParticipant.objects.create(
        event=active_event,
        user=participant_user,
        email=participant_user.email,
        name="Alice",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )
    p2 = CTFParticipant.objects.create(
        event=active_event,
        user=second_participant_user,
        email=second_participant_user.email,
        name="Bob",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )
    p3 = CTFParticipant.objects.create(
        event=active_event,
        email="charlie@test.com",
        name="Charlie",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )
    return p1, p2, p3


def _submit(participant, challenge, correct, points, time_offset_minutes=0):
    """Helper to create a submission with a controllable timestamp."""
    sub = CTFSubmission.objects.create(
        participant=participant,
        challenge=challenge,
        submitted_flag="FLAG{test}",
        is_correct=correct,
        points_awarded=points if correct else 0,
        attempt_number=1,
        ip_address="10.0.0.1",
    )
    if time_offset_minutes:
        # Shift submitted_at after creation (auto_now_add field)
        CTFSubmission.objects.filter(pk=sub.pk).update(
            submitted_at=timezone.now() + timedelta(minutes=time_offset_minutes)
        )
        sub.refresh_from_db()
    return sub


# -----------------------------------------------------------------------------
# calculate_score tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCalculateScore:
    """Tests for calculate_score()."""

    def test_score_sums_correct_submissions_only(self, three_participants, challenges):
        """Correct submissions are summed; incorrect ones are ignored."""
        p1, _, _ = three_participants
        c1, c2, c3 = challenges

        _submit(p1, c1, correct=True, points=100)
        _submit(p1, c2, correct=True, points=200)
        _submit(p1, c3, correct=False, points=0)

        assert calculate_score(p1.id) == 300

    def test_score_zero_with_no_submissions(self, three_participants):
        """Participant with no submissions scores 0."""
        p1, _, _ = three_participants
        assert calculate_score(p1.id) == 0

    def test_score_zero_with_only_incorrect(self, three_participants, challenges):
        """Participant with only incorrect submissions scores 0."""
        p1, _, _ = three_participants
        c1, _, _ = challenges

        _submit(p1, c1, correct=False, points=0)
        _submit(p1, c1, correct=False, points=0)

        assert calculate_score(p1.id) == 0


# -----------------------------------------------------------------------------
# get_scoreboard tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetScoreboard:
    """Tests for get_scoreboard()."""

    def test_ranked_by_score_descending(self, active_event, three_participants, challenges):
        """Higher score = lower rank number."""
        p1, p2, p3 = three_participants
        c1, c2, c3 = challenges

        # p1: 100, p2: 300, p3: 200
        _submit(p1, c1, correct=True, points=100)
        _submit(p2, c2, correct=True, points=200)
        _submit(p2, c1, correct=True, points=100)
        _submit(p3, c3, correct=True, points=200)

        board = get_scoreboard(active_event.id)

        assert board[0]["name"] == "Bob"
        assert board[0]["score"] == 300
        assert board[0]["rank"] == 1

        assert board[1]["name"] == "Charlie"
        assert board[1]["score"] == 200
        assert board[1]["rank"] == 2

        assert board[2]["name"] == "Alice"
        assert board[2]["score"] == 100
        assert board[2]["rank"] == 3

    def test_tie_breaking_by_earlier_last_solve(self, active_event, three_participants, challenges):
        """Same score: participant who solved last challenge earlier ranks higher."""
        p1, p2, _ = three_participants
        c1, _, _ = challenges

        # Both solve c1 for 100 points, but p1 solves earlier
        _submit(p1, c1, correct=True, points=100, time_offset_minutes=-10)
        _submit(p2, c1, correct=True, points=100, time_offset_minutes=0)

        board = get_scoreboard(active_event.id)

        # Both have 100 points, p1 solved earlier
        tied = [e for e in board if e["score"] == 100]
        assert tied[0]["name"] == "Alice"
        assert tied[1]["name"] == "Bob"
        # Same rank for true ties (same score AND same time) — here times differ
        assert tied[0]["rank"] == 1
        assert tied[1]["rank"] == 2

    def test_limit_parameter(self, active_event, three_participants, challenges):
        """Limit restricts the number of scoreboard entries."""
        p1, p2, p3 = three_participants
        c1, c2, c3 = challenges

        _submit(p1, c1, correct=True, points=100)
        _submit(p2, c2, correct=True, points=200)
        _submit(p3, c3, correct=True, points=300)

        board = get_scoreboard(active_event.id, limit=2)
        assert len(board) == 2
        assert board[0]["score"] == 300

    def test_excludes_non_active_statuses(self, active_event, organizer_user, challenges):
        """Only ACTIVE, REGISTERED, and COMPLETED participants appear."""
        c1, _, _ = challenges

        active_p = CTFParticipant.objects.create(
            event=active_event,
            email="active@test.com",
            name="Active",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        disqualified_p = CTFParticipant.objects.create(
            event=active_event,
            email="dq@test.com",
            name="Disqualified",
            status=ParticipantStatus.DISQUALIFIED.value,
            registered_at=timezone.now(),
        )

        _submit(active_p, c1, correct=True, points=100)
        _submit(disqualified_p, c1, correct=True, points=100)

        board = get_scoreboard(active_event.id)
        names = [e["name"] for e in board]
        assert "Active" in names
        assert "Disqualified" not in names

    def test_empty_scoreboard(self, active_event):
        """Event with no participants returns empty list."""
        board = get_scoreboard(active_event.id)
        assert board == []

    def test_scoreboard_includes_solve_count(self, active_event, three_participants, challenges):
        """solve_count reflects number of correct submissions."""
        p1, _, _ = three_participants
        c1, c2, _ = challenges

        _submit(p1, c1, correct=True, points=100)
        _submit(p1, c2, correct=True, points=200)

        board = get_scoreboard(active_event.id)
        p1_entry = next(e for e in board if e["name"] == "Alice")
        assert p1_entry["solve_count"] == 2


# -----------------------------------------------------------------------------
# get_team_scoreboard tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetTeamScoreboard:
    """Tests for get_team_scoreboard()."""

    @pytest.fixture
    def team_event(self, organizer_user):
        """Create a team-mode event with teams and members."""
        event = CTFEvent.objects.create(
            name="Team Scoring Event",
            description="Team scoring test",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
            team_mode=True,
            team_size_limit=4,
        )

        team_a = CTFTeam.objects.create(event=event, name="Alpha")
        team_b = CTFTeam.objects.create(event=event, name="Bravo")

        p1 = CTFParticipant.objects.create(
            event=event,
            email="a1@test.com",
            name="Alpha-1",
            team=team_a,
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        p2 = CTFParticipant.objects.create(
            event=event,
            email="a2@test.com",
            name="Alpha-2",
            team=team_a,
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        p3 = CTFParticipant.objects.create(
            event=event,
            email="b1@test.com",
            name="Bravo-1",
            team=team_b,
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )

        challenge = CTFChallenge.objects.create(
            event=event,
            name="Team Challenge",
            description="Challenge for team scoring",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$team_hash",
        )

        return event, team_a, team_b, (p1, p2, p3), challenge

    def test_team_scores_aggregated(self, team_event):
        """Team score is the sum of all members' correct submissions."""
        event, _team_a, _team_b, (p1, p2, p3), challenge = team_event

        # Alpha: p1=100, p2=100 => 200
        _submit(p1, challenge, correct=True, points=100)
        _submit(p2, challenge, correct=True, points=100)
        # Bravo: p3=100 => 100
        _submit(p3, challenge, correct=True, points=100)

        board = get_team_scoreboard(event.id)

        assert board[0]["name"] == "Alpha"
        assert board[0]["score"] == 200
        assert board[0]["rank"] == 1
        assert board[0]["member_count"] == 2

        assert board[1]["name"] == "Bravo"
        assert board[1]["score"] == 100
        assert board[1]["rank"] == 2

    def test_team_scoreboard_limit(self, team_event):
        """Limit restricts team scoreboard results."""
        event, _, _, (p1, _, p3), challenge = team_event

        _submit(p1, challenge, correct=True, points=100)
        _submit(p3, challenge, correct=True, points=100)

        board = get_team_scoreboard(event.id, limit=1)
        assert len(board) == 1

    def test_team_with_no_solves_scores_zero(self, team_event):
        """Teams with no correct submissions have score 0."""
        event, _, _, _, _ = team_event

        board = get_team_scoreboard(event.id)
        for entry in board:
            assert entry["score"] == 0


# -----------------------------------------------------------------------------
# get_participant_rank tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetParticipantRank:
    """Tests for get_participant_rank()."""

    def test_returns_correct_rank(self, active_event, three_participants, challenges):
        """Rank matches scoreboard position."""
        p1, p2, p3 = three_participants
        c1, c2, c3 = challenges

        _submit(p1, c1, correct=True, points=100)
        _submit(p2, c2, correct=True, points=200)
        _submit(p3, c3, correct=True, points=300)

        assert get_participant_rank(p3.id) == 1
        assert get_participant_rank(p2.id) == 2
        assert get_participant_rank(p1.id) == 3

    def test_returns_none_for_nonexistent_participant(self):
        """Non-existent participant ID returns None."""
        from uuid import uuid4

        assert get_participant_rank(uuid4()) is None

    def test_participant_with_no_submissions_has_rank(self, active_event, three_participants, challenges):
        """Participants with no submissions still appear on scoreboard (rank by 0 score)."""
        p1, p2, _p3 = three_participants
        c1, _, _ = challenges

        # Only p1 has a submission
        _submit(p1, c1, correct=True, points=100)

        rank = get_participant_rank(p1.id)
        assert rank == 1

        # p2 and p3 have 0 score but should still have a rank
        rank_p2 = get_participant_rank(p2.id)
        assert rank_p2 is not None


# -----------------------------------------------------------------------------
# get_challenge_statistics tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetChallengeStatistics:
    """Tests for get_challenge_statistics()."""

    def test_basic_statistics(self, active_event, three_participants, challenges):
        """Returns correct solve count, attempts, and first blood."""
        p1, p2, p3 = three_participants
        c1, _, _ = challenges

        _submit(p1, c1, correct=False, points=0)
        _submit(p1, c1, correct=True, points=100, time_offset_minutes=-5)
        _submit(p2, c1, correct=True, points=100, time_offset_minutes=0)
        _submit(p3, c1, correct=False, points=0)

        stats = get_challenge_statistics(c1.id)

        assert stats["challenge_id"] == str(c1.id)
        assert stats["total_attempts"] == 4
        assert stats["solve_count"] == 2
        assert stats["first_blood"] is not None
        assert stats["first_blood"]["participant_name"] == "Alice"

    def test_no_submissions(self, challenges):
        """Challenge with no submissions returns zero counts."""
        c1, _, _ = challenges

        stats = get_challenge_statistics(c1.id)

        assert stats["total_attempts"] == 0
        assert stats["solve_count"] == 0
        assert stats["first_blood"] is None
        assert stats["solve_rate"] == 0

    def test_nonexistent_challenge(self):
        """Non-existent challenge returns empty dict."""
        from uuid import uuid4

        assert get_challenge_statistics(uuid4()) == {}

    def test_solve_rate(self, active_event, three_participants, challenges):
        """Solve rate = solvers / distinct participants who attempted."""
        p1, p2, _ = three_participants
        c1, _, _ = challenges

        _submit(p1, c1, correct=True, points=100)
        _submit(p2, c1, correct=False, points=0)

        stats = get_challenge_statistics(c1.id)
        # 1 solver out of 2 participants who attempted
        assert stats["solve_rate"] == pytest.approx(0.5)


# -----------------------------------------------------------------------------
# get_event_statistics tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetEventStatistics:
    """Tests for get_event_statistics()."""

    def test_basic_event_stats(self, active_event, three_participants, challenges):
        """Returns correct participant count, challenge count, submissions."""
        p1, p2, _ = three_participants
        c1, c2, _ = challenges

        _submit(p1, c1, correct=True, points=100)
        _submit(p1, c2, correct=False, points=0)
        _submit(p2, c1, correct=True, points=100)

        stats = get_event_statistics(active_event.id)

        assert stats["event_id"] == str(active_event.id)
        assert stats["participant_count"] == 3
        assert stats["active_participants"] == 3
        assert stats["challenge_count"] == 3
        assert stats["total_submissions"] == 3
        assert stats["correct_submissions"] == 2
        assert stats["total_points_awarded"] == 200

    def test_nonexistent_event(self):
        """Non-existent event returns empty dict."""
        from uuid import uuid4

        assert get_event_statistics(uuid4()) == {}

    def test_event_with_no_activity(self, active_event):
        """Event with no participants/submissions returns zero counts."""
        stats = get_event_statistics(active_event.id)

        assert stats["participant_count"] == 0
        assert stats["challenge_count"] == 0
        assert stats["total_submissions"] == 0
        assert stats["total_points_awarded"] == 0


# -----------------------------------------------------------------------------
# calculate_points_with_penalty edge cases (model method)
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCalculatePointsWithPenalty:
    """Tests for CTFChallenge.calculate_points_with_penalty()."""

    def test_no_hint_used_returns_full_points(self, active_event):
        """Not using hint gives full points regardless of penalty setting."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Hint Penalty Test",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$hash_pen",
            hint="A hint",
            hint_penalty=50,
        )
        assert challenge.calculate_points_with_penalty(hint_used=False) == 100

    def test_zero_penalty_returns_full_points(self, active_event):
        """0% penalty gives full points even when hint used."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Zero Penalty Test",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$hash_z",
            hint="A hint",
            hint_penalty=0,
        )
        assert challenge.calculate_points_with_penalty(hint_used=True) == 100

    def test_100_percent_penalty_guarantees_minimum_1_point(self, active_event):
        """100% penalty still awards at least 1 point."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Max Penalty Test",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$hash_m",
            hint="A hint",
            hint_penalty=100,
        )
        result = challenge.calculate_points_with_penalty(hint_used=True)
        assert result == 1

    def test_partial_penalty_reduces_correctly(self, active_event):
        """25% penalty on 200 points = 150 points."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Partial Penalty Test",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=200,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$hash_p",
            hint="A hint",
            hint_penalty=25,
        )
        assert challenge.calculate_points_with_penalty(hint_used=True) == 150

    def test_no_hint_text_no_penalty(self, active_event):
        """Challenge with no hint text returns full points regardless."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="No Hint Test",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$hash_nh",
        )
        assert challenge.calculate_points_with_penalty(hint_used=False) == 100
        assert challenge.calculate_points_with_penalty(hint_used=True) == 100
