"""Tests for CTF award service and score integration.

Integration-style tests covering award grant/revoke and their effect
on score calculation, scoreboards, and model properties.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from ctf.enums import (
    ChallengeCategory,
    ChallengeDifficulty,
    EventStatus,
    ParticipantStatus,
)
from ctf.models import (
    CTFAward,
    CTFChallenge,
    CTFEvent,
    CTFParticipant,
    CTFSubmission,
    CTFTeam,
)
from ctf.services.award import (
    get_event_awards,
    get_participant_awards,
    grant_award,
    revoke_award,
)
from ctf.services.scoring import (
    calculate_score,
    get_event_statistics,
    get_scoreboard,
    get_team_scoreboard,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def active_event(organizer_user):
    """Create an active event for award tests."""
    return CTFEvent.objects.create(
        name="Award Test Event",
        description="Event for award tests",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
    )


@pytest.fixture
def participant(active_event, participant_user):
    """Create an active participant."""
    return CTFParticipant.objects.create(
        event=active_event,
        user=participant_user,
        email=participant_user.email,
        name="Alice",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


@pytest.fixture
def second_participant(active_event, second_participant_user):
    """Create a second active participant."""
    return CTFParticipant.objects.create(
        event=active_event,
        user=second_participant_user,
        email=second_participant_user.email,
        name="Bob",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


@pytest.fixture
def challenge(active_event):
    """Create a challenge."""
    return CTFChallenge.objects.create(
        event=active_event,
        name="Award Test Challenge",
        description="Challenge for award tests",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$award_hash",
    )


def _submit(participant, challenge, correct, points):
    """Helper to create a submission."""
    return CTFSubmission.objects.create(
        participant=participant,
        challenge=challenge,
        submitted_flag="FLAG{test}",
        is_correct=correct,
        points_awarded=points if correct else 0,
        attempt_number=1,
        ip_address="10.0.0.1",
    )


# -----------------------------------------------------------------------------
# TestGrantAward
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGrantAward:
    """Tests for grant_award()."""

    def test_grant_positive_award(self, active_event, participant, organizer_user):
        """Positive award is created successfully."""
        award = grant_award(
            event_id=active_event.id,
            participant_id=participant.id,
            points=50,
            reason="Creative solution bonus",
            granted_by=organizer_user,
        )

        assert award.points == 50
        assert award.reason == "Creative solution bonus"
        assert award.participant == participant
        assert award.event == active_event
        assert award.granted_by == organizer_user

    def test_grant_negative_award(self, active_event, participant, organizer_user):
        """Negative award (deduction) is created successfully."""
        award = grant_award(
            event_id=active_event.id,
            participant_id=participant.id,
            points=-25,
            reason="Rule violation penalty",
            granted_by=organizer_user,
        )

        assert award.points == -25

    def test_wrong_event_raises_error(self, active_event, participant, organizer_user):
        """Participant not in the specified event raises CTFValidationError."""
        from ctf.exceptions import CTFValidationError

        other_event = CTFEvent.objects.create(
            name="Other Event",
            description="Different event",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
        )

        with pytest.raises(CTFValidationError, match="does not belong"):
            grant_award(
                event_id=other_event.id,
                participant_id=participant.id,
                points=50,
                reason="Should fail",
                granted_by=organizer_user,
            )

    def test_nonexistent_participant_raises_error(self, active_event, organizer_user):
        """Non-existent participant raises CTFNotFoundError."""
        from ctf.exceptions import CTFNotFoundError

        with pytest.raises(CTFNotFoundError):
            grant_award(
                event_id=active_event.id,
                participant_id=uuid4(),
                points=50,
                reason="Should fail",
                granted_by=organizer_user,
            )

    def test_nonexistent_event_raises_error(self, participant, organizer_user):
        """Non-existent event raises CTFNotFoundError."""
        from ctf.exceptions import CTFNotFoundError

        with pytest.raises(CTFNotFoundError):
            grant_award(
                event_id=uuid4(),
                participant_id=participant.id,
                points=50,
                reason="Should fail",
                granted_by=organizer_user,
            )


# -----------------------------------------------------------------------------
# TestRevokeAward
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestRevokeAward:
    """Tests for revoke_award()."""

    def test_soft_delete_works(self, active_event, participant, organizer_user):
        """Revoking an award soft-deletes it."""
        award = grant_award(
            event_id=active_event.id,
            participant_id=participant.id,
            points=50,
            reason="Bonus",
            granted_by=organizer_user,
        )

        revoke_award(award.id)

        # Should not appear in default queryset
        assert CTFAward.objects.filter(pk=award.id).count() == 0
        # Should still exist in all_objects
        assert CTFAward.all_objects.filter(pk=award.id).count() == 1

    def test_revoked_award_not_counted_in_score(self, active_event, participant, organizer_user):
        """Revoked awards are excluded from score calculation."""
        grant_award(
            event_id=active_event.id,
            participant_id=participant.id,
            points=50,
            reason="Bonus",
            granted_by=organizer_user,
        )

        assert calculate_score(participant.id) == 50

        # Revoke the award
        award = CTFAward.objects.filter(participant=participant).first()
        revoke_award(award.id)

        assert calculate_score(participant.id) == 0

    def test_revoke_nonexistent_raises_error(self):
        """Revoking a non-existent award raises CTFNotFoundError."""
        from ctf.exceptions import CTFNotFoundError

        with pytest.raises(CTFNotFoundError):
            revoke_award(uuid4())


# -----------------------------------------------------------------------------
# TestGetAwards
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetAwards:
    """Tests for get_participant_awards() and get_event_awards()."""

    def test_get_participant_awards(self, active_event, participant, organizer_user):
        """Returns awards for the specified participant only."""
        grant_award(active_event.id, participant.id, 50, "Bonus 1", organizer_user)
        grant_award(active_event.id, participant.id, 25, "Bonus 2", organizer_user)

        awards = get_participant_awards(participant.id)
        assert awards.count() == 2

    def test_get_event_awards(self, active_event, participant, second_participant, organizer_user):
        """Returns all awards for the event."""
        grant_award(active_event.id, participant.id, 50, "Bonus", organizer_user)
        grant_award(active_event.id, second_participant.id, 30, "Bonus", organizer_user)

        awards = get_event_awards(active_event.id)
        assert awards.count() == 2


# -----------------------------------------------------------------------------
# TestScoreWithAwards
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestScoreWithAwards:
    """Tests for score calculations that include awards."""

    def test_calculate_score_includes_awards(self, active_event, participant, challenge, organizer_user):
        """calculate_score sums submissions and awards."""
        _submit(participant, challenge, correct=True, points=100)
        grant_award(active_event.id, participant.id, 50, "Bonus", organizer_user)

        assert calculate_score(participant.id) == 150

    def test_negative_awards_reduce_score(self, active_event, participant, challenge, organizer_user):
        """Negative awards reduce the total score."""
        _submit(participant, challenge, correct=True, points=100)
        grant_award(active_event.id, participant.id, -30, "Penalty", organizer_user)

        assert calculate_score(participant.id) == 70

    def test_awards_only_score(self, active_event, participant, organizer_user):
        """Score works with awards only (no submissions)."""
        grant_award(active_event.id, participant.id, 75, "Manual credit", organizer_user)

        assert calculate_score(participant.id) == 75

    def test_scoreboard_ranking_reflects_awards(
        self, active_event, participant, second_participant, challenge, organizer_user
    ):
        """Awards change scoreboard rankings."""
        # Both solve for 100
        _submit(participant, challenge, correct=True, points=100)
        _submit(second_participant, challenge, correct=True, points=100)

        # Give Bob a bonus
        grant_award(active_event.id, second_participant.id, 50, "Bonus", organizer_user)

        board = get_scoreboard(active_event.id)

        assert board[0]["name"] == "Bob"
        assert board[0]["score"] == 150
        assert board[0]["rank"] == 1

        assert board[1]["name"] == "Alice"
        assert board[1]["score"] == 100
        assert board[1]["rank"] == 2

    def test_team_scoreboard_reflects_awards(self, organizer_user):
        """Team scoreboard includes member awards."""
        event = CTFEvent.objects.create(
            name="Team Award Event",
            description="Team award test",
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
            email="b1@test.com",
            name="Bravo-1",
            team=team_b,
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )

        challenge = CTFChallenge.objects.create(
            event=event,
            name="Team Challenge",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$th",
        )

        # Both teams solve for 100
        _submit(p1, challenge, correct=True, points=100)
        _submit(p2, challenge, correct=True, points=100)

        # Give Alpha member a bonus
        grant_award(event.id, p1.id, 50, "Bonus", organizer_user)

        board = get_team_scoreboard(event.id)

        assert board[0]["name"] == "Alpha"
        assert board[0]["score"] == 150
        assert board[1]["name"] == "Bravo"
        assert board[1]["score"] == 100

    def test_participant_total_score_property(self, active_event, participant, challenge, organizer_user):
        """CTFParticipant.total_score property includes awards."""
        _submit(participant, challenge, correct=True, points=100)
        grant_award(active_event.id, participant.id, 25, "Bonus", organizer_user)

        participant.refresh_from_db()
        assert participant.total_score == 125

    def test_team_total_score_property(self, organizer_user):
        """CTFTeam.total_score property includes member awards."""
        event = CTFEvent.objects.create(
            name="Team Prop Event",
            description="Test",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
            team_mode=True,
            team_size_limit=4,
        )

        team = CTFTeam.objects.create(event=event, name="TestTeam")
        p1 = CTFParticipant.objects.create(
            event=event,
            email="tp1@test.com",
            name="TP1",
            team=team,
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )

        challenge = CTFChallenge.objects.create(
            event=event,
            name="TP Challenge",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$tp",
        )

        _submit(p1, challenge, correct=True, points=100)
        grant_award(event.id, p1.id, 30, "Bonus", organizer_user)

        team.refresh_from_db()
        assert team.total_score == 130

    def test_event_statistics_includes_total_awards(self, active_event, participant, organizer_user):
        """get_event_statistics includes total_awards count."""
        grant_award(active_event.id, participant.id, 50, "Bonus 1", organizer_user)
        grant_award(active_event.id, participant.id, 25, "Bonus 2", organizer_user)

        stats = get_event_statistics(active_event.id)
        assert stats["total_awards"] == 2
