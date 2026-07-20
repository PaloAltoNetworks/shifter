"""Real-DB behavior tests for ``ctf.services.scoring`` (issue #850).

Replaces the prior all-mocked suite. These exercise the materialized leaderboard
read paths against a real (sqlite) test database and cross-check them against the
authoritative recompute, plus the incremental-maintenance helpers/hooks, the
participant-rank path, and the query-count guarantees that the materialized
design exists to provide.

Challenge / event statistics and the score timeline keep their own suites
(``test_scoring_statistics.py``, ``test_scoring_timeline.py``).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus, ParticipantStatus
from ctf.models import CTFAward, CTFChallenge, CTFEvent, CTFParticipant, CTFSubmission, CTFTeam
from ctf.services.scoring import (
    calculate_score,
    get_participant_rank,
    get_scoreboard,
    get_team_scoreboard,
    recompute_event_leaderboard,
    recompute_participant_score,
)

pytestmark = pytest.mark.django_db

# A freeze cutoff far in the future forces ``get_scoreboard`` /
# ``get_team_scoreboard`` down the authoritative recompute path while still
# counting every submission/award, so the recompute result is directly
# comparable to the live materialized read.
_FAR_FUTURE = timezone.now() + timedelta(days=3650)


# ---------------------------------------------------------------------------
# Builders (persisted)
# ---------------------------------------------------------------------------


def _make_event(organizer, *, team_mode: bool = False) -> CTFEvent:
    now = timezone.now()
    return CTFEvent.objects.create(
        name=f"Event {uuid4().hex[:8]}",
        description="scoring behavior test event",
        created_by=organizer,
        status=EventStatus.ACTIVE.value,
        event_start=now - timedelta(hours=1),
        event_end=now + timedelta(hours=7),
        scenario_id="basic",
        team_mode=team_mode,
        team_size_limit=4 if team_mode else None,
    )


def _make_challenge(event: CTFEvent, *, points: int = 100, name: str | None = None) -> CTFChallenge:
    return CTFChallenge.objects.create(
        event=event,
        name=name or f"Challenge {uuid4().hex[:8]}",
        description="x",
        category=ChallengeCategory.WEB.value,
        points=points,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$placeholder",
        flag_format="FLAG{...}",
    )


def _make_participant(
    event: CTFEvent,
    name: str,
    *,
    status: str = ParticipantStatus.ACTIVE.value,
    registered: bool = True,
    team: CTFTeam | None = None,
    bracket=None,
) -> CTFParticipant:
    return CTFParticipant.objects.create(
        event=event,
        email=f"{name}-{uuid4().hex[:8]}@t.test",
        name=name,
        status=status,
        registered_at=timezone.now() if registered else None,
        team=team,
        bracket=bracket,
    )


def _solve(participant, challenge, *, points: int, at=None) -> CTFSubmission:
    """Create a correct submission, optionally overriding the auto ``submitted_at``."""
    sub = CTFSubmission.objects.create(
        participant=participant,
        challenge=challenge,
        submitted_flag="FLAG{x}",
        is_correct=True,
        points_awarded=points,
        attempt_number=1,
    )
    if at is not None:
        CTFSubmission.objects.filter(pk=sub.pk).update(submitted_at=at)
    return sub


def _award(event, participant, points: int, organizer) -> CTFAward:
    return CTFAward.objects.create(
        event=event,
        participant=participant,
        points=points,
        reason="bonus",
        granted_by=organizer,
    )


def _by_participant(board: list[dict]) -> dict[str, tuple]:
    """Order-independent view of an individual board keyed by participant id."""
    return {r["participant_id"]: (r["rank"], r["score"], r["solve_count"], r["last_solve"]) for r in board}


def _by_team(board: list[dict]) -> dict[str, tuple]:
    """Order-independent view of a team board keyed by team id."""
    return {r["team_id"]: (r["rank"], r["score"], r["solve_count"], r["member_count"], r["last_solve"]) for r in board}


# ---------------------------------------------------------------------------
# Materialized vs authoritative-recompute equivalence
# ---------------------------------------------------------------------------


class TestMaterializedEquivalence:
    """The live materialized read must equal the authoritative recompute."""

    def test_individual_board_matches_recompute(self, organizer_user):
        event = _make_event(organizer_user)
        c1 = _make_challenge(event, points=100)
        c2 = _make_challenge(event, points=200)
        now = timezone.now()

        alice = _make_participant(event, "Alice")
        bob = _make_participant(event, "Bob")
        carol = _make_participant(event, "Carol")
        _make_participant(event, "NoSolve")  # eligible, zero score
        dq = _make_participant(event, "Disq", status=ParticipantStatus.DISQUALIFIED.value)

        _solve(alice, c1, points=100, at=now - timedelta(minutes=30))
        _solve(bob, c1, points=100, at=now - timedelta(minutes=20))
        _solve(bob, c2, points=200, at=now - timedelta(minutes=10))
        _solve(carol, c2, points=200, at=now - timedelta(minutes=5))
        _award(event, alice, 50, organizer_user)
        _solve(dq, c1, points=100, at=now - timedelta(minutes=1))  # excluded (disqualified)

        recompute_event_leaderboard(event.id)

        materialized = get_scoreboard(event.id)
        authoritative = get_scoreboard(event.id, freeze_at=_FAR_FUTURE)

        assert _by_participant(materialized) == _by_participant(authoritative)
        # Disqualified participant never appears.
        assert str(dq.id) not in _by_participant(materialized)
        # Spot-check the actual ranking: Bob 300 (rank1), Carol 200 (rank2),
        # Alice 150 (rank3), NoSolve 0 (rank4).
        ranks = {r["name"]: r["rank"] for r in materialized}
        assert ranks == {"Bob": 1, "Carol": 2, "Alice": 3, "NoSolve": 4}

    def test_team_board_matches_recompute(self, organizer_user):
        event = _make_event(organizer_user, team_mode=True)
        c1 = _make_challenge(event, points=100)
        c2 = _make_challenge(event, points=200)
        now = timezone.now()

        alpha = CTFTeam.objects.create(event=event, name="Alpha")
        bravo = CTFTeam.objects.create(event=event, name="Bravo")
        CTFTeam.objects.create(event=event, name="Empty")

        a1 = _make_participant(event, "A1", team=alpha)
        a2 = _make_participant(event, "A2", team=alpha)
        b1 = _make_participant(event, "B1", team=bravo)
        # Disqualified Alpha member: contributions must not count.
        a_dq = _make_participant(event, "Adq", team=alpha, status=ParticipantStatus.DISQUALIFIED.value)

        _solve(a1, c1, points=100, at=now - timedelta(minutes=30))
        _solve(a2, c2, points=200, at=now - timedelta(minutes=20))
        _solve(b1, c1, points=100, at=now - timedelta(minutes=10))
        _award(event, a1, 25, organizer_user)
        _solve(a_dq, c2, points=200, at=now - timedelta(minutes=1))

        recompute_event_leaderboard(event.id)

        materialized = get_team_scoreboard(event.id)
        authoritative = get_team_scoreboard(event.id, freeze_at=_FAR_FUTURE)
        assert _by_team(materialized) == _by_team(authoritative)

        stats = {r["name"]: r for r in materialized}
        assert stats["Alpha"]["score"] == 325  # 100 + 200 + 25 award; dq excluded
        assert stats["Alpha"]["solve_count"] == 2  # two distinct challenges
        assert stats["Alpha"]["member_count"] == 2  # eligible only
        assert stats["Bravo"]["score"] == 100
        assert stats["Empty"]["score"] == 0
        assert stats["Empty"]["member_count"] == 0

    def test_team_score_dedupes_shared_challenge_solves(self, organizer_user):
        # #1138: two teammates solving the SAME challenge count once for the
        # team, at the best (max) points — not summed twice. Asserts both the
        # materialized and the frozen/authoritative recompute paths agree.
        event = _make_event(organizer_user, team_mode=True)
        c1 = _make_challenge(event, points=100)
        now = timezone.now()

        team = CTFTeam.objects.create(event=event, name="Dup")
        m1 = _make_participant(event, "M1", team=team)
        m2 = _make_participant(event, "M2", team=team)

        _solve(m1, c1, points=100, at=now - timedelta(minutes=20))
        # Same challenge, fewer points (e.g. a hint penalty) for the second solver.
        _solve(m2, c1, points=80, at=now - timedelta(minutes=10))

        recompute_event_leaderboard(event.id)

        materialized = get_team_scoreboard(event.id)
        authoritative = get_team_scoreboard(event.id, freeze_at=_FAR_FUTURE)
        assert _by_team(materialized) == _by_team(authoritative)

        stats = {r["name"]: r for r in materialized}
        # Counted once at the max (100), not 100 + 80.
        assert stats["Dup"]["score"] == 100
        assert stats["Dup"]["solve_count"] == 1


# ---------------------------------------------------------------------------
# Scoreboard behavior contract
# ---------------------------------------------------------------------------


class TestScoreboardBehavior:
    def test_ranked_by_score_descending(self, organizer_user):
        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        now = timezone.now()
        for name, pts in [("Bob", 300), ("Charlie", 200), ("Alice", 100)]:
            p = _make_participant(event, name)
            _solve(p, c, points=pts, at=now - timedelta(minutes=10))
        recompute_event_leaderboard(event.id)

        board = get_scoreboard(event.id)
        assert [(r["name"], r["rank"]) for r in board] == [("Bob", 1), ("Charlie", 2), ("Alice", 3)]

    def test_tie_breaking_by_earlier_last_solve(self, organizer_user):
        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        now = timezone.now()
        alice = _make_participant(event, "Alice")
        bob = _make_participant(event, "Bob")
        _solve(alice, c, points=100, at=now - timedelta(minutes=10))  # earlier
        _solve(bob, c, points=100, at=now - timedelta(minutes=5))  # later
        recompute_event_leaderboard(event.id)

        board = get_scoreboard(event.id)
        assert [(r["name"], r["rank"]) for r in board] == [("Alice", 1), ("Bob", 2)]

    def test_limit(self, organizer_user):
        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        now = timezone.now()
        for i, pts in enumerate([300, 200, 100]):
            _solve(_make_participant(event, f"P{i}"), c, points=pts, at=now - timedelta(minutes=10))
        recompute_event_leaderboard(event.id)

        board = get_scoreboard(event.id, limit=2)
        assert len(board) == 2
        assert board[0]["score"] == 300

    def test_excludes_non_eligible(self, organizer_user):
        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        active = _make_participant(event, "Active")
        _make_participant(event, "Invited", status=ParticipantStatus.INVITED.value, registered=False)
        _make_participant(event, "Disq", status=ParticipantStatus.DISQUALIFIED.value)
        _solve(active, c, points=100)
        recompute_event_leaderboard(event.id)

        names = [r["name"] for r in get_scoreboard(event.id)]
        assert names == ["Active"]

    def test_empty(self, organizer_user):
        event = _make_event(organizer_user)
        assert get_scoreboard(event.id) == []

    def test_solve_count_and_zero_score_participants(self, organizer_user):
        event = _make_event(organizer_user)
        c1 = _make_challenge(event, points=100)
        c2 = _make_challenge(event, points=100)
        solver = _make_participant(event, "Solver")
        _make_participant(event, "Idle")
        _solve(solver, c1, points=100)
        _solve(solver, c2, points=100)
        recompute_event_leaderboard(event.id)

        board = {r["name"]: r for r in get_scoreboard(event.id)}
        assert board["Solver"]["solve_count"] == 2
        assert board["Idle"]["solve_count"] == 0
        assert board["Idle"]["score"] == 0
        assert board["Idle"]["rank"] == 2  # still ranked

    def test_bracket_filter(self, organizer_user):
        from ctf.models import CTFBracket

        event = _make_event(organizer_user)
        beginner = CTFBracket.objects.create(event=event, name="Beginner")
        advanced = CTFBracket.objects.create(event=event, name="Advanced")
        c = _make_challenge(event, points=100)
        b_player = _make_participant(event, "Beg", bracket=beginner)
        a_player = _make_participant(event, "Adv", bracket=advanced)
        _solve(b_player, c, points=100)
        _solve(a_player, c, points=100)
        recompute_event_leaderboard(event.id)

        names = [r["name"] for r in get_scoreboard(event.id, bracket_id=beginner.id)]
        assert names == ["Beg"]


# ---------------------------------------------------------------------------
# Participant rank
# ---------------------------------------------------------------------------


class TestParticipantRank:
    def test_ranks_match_board(self, organizer_user):
        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        now = timezone.now()
        charlie = _make_participant(event, "Charlie")
        bob = _make_participant(event, "Bob")
        alice = _make_participant(event, "Alice")
        _solve(charlie, c, points=300, at=now - timedelta(minutes=10))
        _solve(bob, c, points=200, at=now - timedelta(minutes=10))
        _solve(alice, c, points=100, at=now - timedelta(minutes=10))
        recompute_event_leaderboard(event.id)

        assert get_participant_rank(charlie.id) == 1
        assert get_participant_rank(bob.id) == 2
        assert get_participant_rank(alice.id) == 3

    def test_tied_participants_share_rank(self, organizer_user):
        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        now = timezone.now()
        # Two exact ties (same score, same last-solve) then a lower score.
        p1 = _make_participant(event, "P1")
        p2 = _make_participant(event, "P2")
        low = _make_participant(event, "Low")
        same = now - timedelta(minutes=10)
        _solve(p1, c, points=100, at=same)
        _solve(p2, c, points=100, at=same)
        _solve(low, c, points=50, at=now - timedelta(minutes=5))
        recompute_event_leaderboard(event.id)

        assert get_participant_rank(p1.id) == 1
        assert get_participant_rank(p2.id) == 1  # shares rank 1 (competition ranking)
        assert get_participant_rank(low.id) == 3  # 1 + 2 ahead

    def test_zero_score_participant_has_rank(self, organizer_user):
        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        leader = _make_participant(event, "Leader")
        idle = _make_participant(event, "Idle")
        _solve(leader, c, points=100)
        recompute_event_leaderboard(event.id)

        assert get_participant_rank(leader.id) == 1
        assert get_participant_rank(idle.id) == 2

    def test_nonexistent_returns_none(self):
        assert get_participant_rank(uuid4()) is None

    def test_ineligible_returns_none(self, organizer_user):
        event = _make_event(organizer_user)
        dq = _make_participant(event, "Disq", status=ParticipantStatus.DISQUALIFIED.value)
        recompute_event_leaderboard(event.id)
        assert get_participant_rank(dq.id) is None


# ---------------------------------------------------------------------------
# Incremental maintenance helpers + hooks
# ---------------------------------------------------------------------------


class TestMaintenance:
    def test_recompute_participant_from_submissions_and_awards(self, organizer_user):
        event = _make_event(organizer_user)
        c1 = _make_challenge(event, points=100)
        c2 = _make_challenge(event, points=200)
        now = timezone.now()
        p = _make_participant(event, "P")
        _solve(p, c1, points=100, at=now - timedelta(minutes=20))
        last = _solve(p, c2, points=200, at=now - timedelta(minutes=5))
        _award(event, p, 25, organizer_user)

        recompute_participant_score(p.id)
        p.refresh_from_db()
        assert p.cached_score == 325
        assert p.cached_solve_count == 2
        assert p.last_solve_at == CTFSubmission.objects.get(pk=last.pk).submitted_at

    def test_recompute_participant_no_solves(self, organizer_user):
        event = _make_event(organizer_user)
        p = _make_participant(event, "P")
        recompute_participant_score(p.id)
        p.refresh_from_db()
        assert p.cached_score == 0
        assert p.cached_solve_count == 0
        assert p.last_solve_at is None

    def test_grant_award_updates_cached_score(self, organizer_user):
        from ctf.services.award import grant_award

        event = _make_event(organizer_user)
        p = _make_participant(event, "P")
        recompute_participant_score(p.id)
        grant_award(event.id, p.id, 75, "bonus", organizer_user)
        p.refresh_from_db()
        assert p.cached_score == 75

    def test_revoke_award_updates_cached_score(self, organizer_user):
        from ctf.services.award import grant_award, revoke_award

        event = _make_event(organizer_user)
        p = _make_participant(event, "P")
        award = grant_award(event.id, p.id, 75, "bonus", organizer_user)
        p.refresh_from_db()
        assert p.cached_score == 75
        revoke_award(award.id)
        p.refresh_from_db()
        assert p.cached_score == 0

    def test_disqualify_drops_team_contribution(self, organizer_user):
        from ctf.services.participant import disqualify_participant

        event = _make_event(organizer_user, team_mode=True)
        # Distinct challenges so each member's contribution is independent; a
        # shared challenge would dedupe to a single count (see #1138).
        c1 = _make_challenge(event, points=100)
        c2 = _make_challenge(event, points=100)
        team = CTFTeam.objects.create(event=event, name="Alpha")
        keep = _make_participant(event, "Keep", team=team)
        drop = _make_participant(event, "Drop", team=team)
        _solve(keep, c1, points=100)
        _solve(drop, c2, points=100)
        recompute_event_leaderboard(event.id)
        team.refresh_from_db()
        assert team.cached_score == 200
        assert team.cached_member_count == 2

        disqualify_participant(drop.id)
        team.refresh_from_db()
        assert team.cached_score == 100  # dropped member's solve removed
        assert team.cached_member_count == 1

    def test_submit_flag_hook_updates_cached_columns(self, organizer_user):
        from ctf.services.challenge import hash_flag
        from ctf.services.submission import submit_flag

        event = _make_event(organizer_user)
        challenge = _make_challenge(event)
        CTFChallenge.objects.filter(pk=challenge.pk).update(flag_hash=hash_flag("FLAG{win}"))
        participant = _make_participant(event, "P")

        submit_flag(participant.id, challenge.id, "FLAG{win}")
        participant.refresh_from_db()
        assert participant.cached_score == 100
        assert participant.cached_solve_count == 1
        assert participant.last_solve_at is not None

    def test_recompute_event_scoped(self, organizer_user):
        event_a = _make_event(organizer_user)
        event_b = _make_event(organizer_user)
        ca = _make_challenge(event_a, points=100)
        cb = _make_challenge(event_b, points=100)
        pa = _make_participant(event_a, "A")
        pb = _make_participant(event_b, "B")
        _solve(pa, ca, points=100)
        _solve(pb, cb, points=100)

        participants, _teams = recompute_event_leaderboard(event_a.id)
        assert participants == 1  # only event_a
        pa.refresh_from_db()
        pb.refresh_from_db()
        assert pa.cached_score == 100
        assert pb.cached_score == 0  # event_b untouched


# ---------------------------------------------------------------------------
# Query-count guarantees (the point of materializing)
# ---------------------------------------------------------------------------


class TestQueryCounts:
    def test_scoreboard_query_count_constant_in_participants(self, organizer_user):
        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        for i in range(40):
            p = _make_participant(event, f"P{i}")
            _solve(p, c, points=(i + 1) * 10)
        recompute_event_leaderboard(event.id)

        with CaptureQueriesContext(connection) as ctx:
            board = get_scoreboard(event.id)
        assert len(board) == 40
        # Materialized read is a single indexed query (plus select_related joins);
        # it must not issue a query per participant.
        assert len(ctx.captured_queries) <= 3

    def test_participant_rank_query_count_constant(self, organizer_user):
        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        target = _make_participant(event, "Target")
        _solve(target, c, points=500)
        for i in range(40):
            p = _make_participant(event, f"P{i}")
            _solve(p, c, points=(i + 1) * 10)
        recompute_event_leaderboard(event.id)

        with CaptureQueriesContext(connection) as ctx:
            rank = get_participant_rank(target.id)
        assert rank == 1
        # get + eligibility-exists + count == a small constant, not O(participants).
        assert len(ctx.captured_queries) <= 4


# ---------------------------------------------------------------------------
# calculate_score (authoritative helper)
# ---------------------------------------------------------------------------


class TestRecomputeCommand:
    def test_command_rebuilds_materialized_columns(self, organizer_user):
        from django.core.management import call_command

        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        p = _make_participant(event, "P")
        # Insert a submission directly (no hook), leaving cached_score stale.
        _solve(p, c, points=100)
        p.refresh_from_db()
        assert p.cached_score == 0

        call_command("ctf_recompute_leaderboard")
        p.refresh_from_db()
        assert p.cached_score == 100

    def test_command_event_scope(self, organizer_user):
        from django.core.management import call_command

        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        p = _make_participant(event, "P")
        _solve(p, c, points=100)

        call_command("ctf_recompute_leaderboard", "--event", str(event.id))
        p.refresh_from_db()
        assert p.cached_score == 100

    def test_command_rejects_invalid_event_uuid(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command("ctf_recompute_leaderboard", "--event", "not-a-uuid")


class TestCalculateScore:
    def test_sums_correct_submissions_and_awards(self, organizer_user):
        event = _make_event(organizer_user)
        c = _make_challenge(event, points=100)
        p = _make_participant(event, "P")
        _solve(p, c, points=100)
        _award(event, p, 50, organizer_user)
        # An incorrect submission must not count.
        CTFSubmission.objects.create(
            participant=p, challenge=c, submitted_flag="nope", is_correct=False, points_awarded=0, attempt_number=2
        )
        assert calculate_score(p.id) == 150

    def test_zero_with_no_activity(self, organizer_user):
        event = _make_event(organizer_user)
        p = _make_participant(event, "P")
        assert calculate_score(p.id) == 0
