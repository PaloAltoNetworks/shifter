"""Tests for CTF models.

Following TDD approach - these tests define expected model behavior.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from ctf.enums import (
    ChallengeCategory,
    ChallengeDifficulty,
    EventStatus,
    ParticipantStatus,
    ScheduledTaskStatus,
)
from ctf.models import (
    CTFChallenge,
    CTFEvent,
    CTFParticipant,
    CTFScheduledTask,
    CTFSubmission,
    CTFTeam,
)
from ctf.tests.factories import (
    create_challenge_model_data,
    create_submission_data,
)

# -----------------------------------------------------------------------------
# CTFEvent Model Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFEventModel:
    """Tests for CTFEvent model."""

    def test_create_event_with_required_fields(self, organizer_user):
        """Test creating event with minimum required fields."""
        event = CTFEvent.objects.create(
            name="Test Event",
            created_by=organizer_user,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
        )

        assert event.id is not None
        assert event.name == "Test Event"
        assert event.status == EventStatus.DRAFT.value
        assert event.auto_cleanup is True
        assert event.cleanup_delay_hours == 24
        assert event.scenario_id == "basic"

    def test_event_str_representation(self, ctf_event):
        """Test event string representation."""
        assert str(ctf_event) == "Test CTF Event"

    def test_event_is_active_property(self, ctf_event_active):
        """Test is_active property for active event."""
        assert ctf_event_active.is_active is True

    def test_event_is_active_false_for_draft(self, ctf_event_draft):
        """Test is_active property for draft event."""
        assert ctf_event_draft.is_active is False

    def test_event_is_upcoming_property(self, ctf_event):
        """Test is_upcoming property for scheduled event."""
        assert ctf_event.is_upcoming is True

    def test_event_is_modifiable_for_draft(self, ctf_event_draft):
        """Test is_modifiable for draft event."""
        assert ctf_event_draft.is_modifiable is True

    def test_event_is_modifiable_for_completed(self, ctf_event):
        """Test is_modifiable for completed event."""
        ctf_event.status = EventStatus.COMPLETED.value
        ctf_event.save()
        assert ctf_event.is_modifiable is False

    def test_event_duration_hours(self, ctf_event):
        """Test duration_hours calculation."""
        assert ctf_event.duration_hours == pytest.approx(8.0)

    def test_event_participant_count(self, ctf_event, ctf_participant):
        """Test participant_count property."""
        assert ctf_event.participant_count == 1

    def test_event_challenge_count(self, ctf_event, ctf_challenge):
        """Test challenge_count property."""
        assert ctf_event.challenge_count == 1

    def test_event_get_cleanup_time(self, ctf_event):
        """Test get_cleanup_time calculation."""
        expected = ctf_event.event_end + timedelta(hours=24)
        assert ctf_event.get_cleanup_time() == expected

    def test_event_get_spinup_time(self, ctf_event):
        """Test get_spinup_time calculation."""
        expected = ctf_event.event_start - timedelta(minutes=30)
        assert ctf_event.get_spinup_time() == expected

    def test_event_validation_end_before_start_fails(self, organizer_user):
        """Test validation rejects end time before start time."""
        with pytest.raises(ValidationError) as exc_info:
            event = CTFEvent(
                name="Invalid Event",
                created_by=organizer_user,
                event_start=timezone.now() + timedelta(days=2),
                event_end=timezone.now() + timedelta(days=1),
            )
            event.full_clean()

        assert "event_end" in exc_info.value.message_dict

    def test_event_validation_team_mode_requires_size_limit(self, organizer_user):
        """Test validation requires team_size_limit when team_mode is True."""
        with pytest.raises(ValidationError) as exc_info:
            event = CTFEvent(
                name="Team Event",
                created_by=organizer_user,
                event_start=timezone.now() + timedelta(days=1),
                event_end=timezone.now() + timedelta(days=1, hours=8),
                team_mode=True,
                team_size_limit=None,
            )
            event.full_clean()

        assert "team_size_limit" in exc_info.value.message_dict

    def test_event_soft_delete(self, ctf_event):
        """Test soft delete functionality."""
        event_id = ctf_event.id
        ctf_event.delete(soft=True)

        # Should still exist with all_objects
        assert CTFEvent.all_objects.filter(pk=event_id).exists()

        # Should not appear in default queryset
        assert not CTFEvent.objects.filter(pk=event_id).exists()

        # is_deleted should be True
        ctf_event.refresh_from_db()
        assert ctf_event.is_deleted is True

    def test_event_restore(self, ctf_event):
        """Test restoring a soft-deleted event."""
        ctf_event.delete(soft=True)
        assert ctf_event.is_deleted is True

        ctf_event.restore()
        assert ctf_event.is_deleted is False
        assert CTFEvent.objects.filter(pk=ctf_event.id).exists()


# -----------------------------------------------------------------------------
# CTFChallenge Model Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFChallengeModel:
    """Tests for CTFChallenge model."""

    def test_create_challenge(self, ctf_event):
        """Test creating a challenge."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event,
            **create_challenge_model_data(),
        )

        assert challenge.id is not None
        assert challenge.event == ctf_event
        assert challenge.points == 100

    def test_challenge_str_representation(self, ctf_challenge):
        """Test challenge string representation."""
        assert str(ctf_challenge) == "[web] Test Challenge"

    def test_challenge_is_released_no_release_time(self, ctf_challenge):
        """Test is_released when no release_time set."""
        assert ctf_challenge.is_released is True

    def test_challenge_is_released_future_time(self, ctf_challenge_delayed):
        """Test is_released for future release time."""
        assert ctf_challenge_delayed.is_released is False

    def test_challenge_solve_count(self, ctf_challenge, ctf_submission_correct):
        """Test solve_count property."""
        assert ctf_challenge.solve_count == 1

    def test_challenge_first_blood(self, ctf_challenge, ctf_submission_correct):
        """Test first_blood property."""
        first = ctf_challenge.first_blood
        assert first == ctf_submission_correct

    def test_challenge_calculate_points_no_penalty(self, ctf_challenge):
        """Test points calculation without hint penalty."""
        points = ctf_challenge.calculate_points_with_penalty(hint_used=False)
        assert points == 100

    def test_challenge_calculate_points_with_penalty(self, ctf_challenge_with_hint):
        """Test points calculation with hint penalty."""
        # 25% of 200 = 50, so 200 - 50 = 150
        points = ctf_challenge_with_hint.calculate_points_with_penalty(hint_used=True)
        assert points == 150

    def test_challenge_validation_hint_penalty_without_hint(self, ctf_event):
        """Test validation rejects hint_penalty without hint."""
        with pytest.raises(ValidationError) as exc_info:
            challenge = CTFChallenge(
                event=ctf_event,
                name="Invalid Challenge",
                description="Test",
                category=ChallengeCategory.WEB.value,
                points=100,
                difficulty=ChallengeDifficulty.EASY.value,
                flag_hash="test",
                hint="",  # No hint
                hint_penalty=25,  # But penalty set
            )
            challenge.full_clean()

        assert "hint_penalty" in exc_info.value.message_dict

    def test_challenge_unique_name_per_event(self, ctf_event, ctf_challenge):
        """Test unique constraint on challenge name per event."""
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            CTFChallenge.objects.create(
                event=ctf_event,
                name=ctf_challenge.name,  # Same name
                description="Another challenge",
                category=ChallengeCategory.CRYPTO.value,
                points=200,
                difficulty=ChallengeDifficulty.HARD.value,
                flag_hash="different_hash",
            )

    def test_challenge_ordering(self, ctf_event):
        """Test challenges are ordered by category, order, name."""
        c3 = CTFChallenge.objects.create(
            event=ctf_event,
            name="Zebra",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="h1",
            order=2,
        )
        c1 = CTFChallenge.objects.create(
            event=ctf_event,
            name="Alpha",
            description="Test",
            category=ChallengeCategory.CRYPTO.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="h2",
            order=0,
        )
        c2 = CTFChallenge.objects.create(
            event=ctf_event,
            name="Beta",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="h3",
            order=1,
        )

        challenges = list(ctf_event.challenges.all())
        # Ordered by category (crypto < web), then order, then name
        assert challenges[0] == c1  # crypto, order 0
        assert challenges[1] == c2  # web, order 1
        assert challenges[2] == c3  # web, order 2


# -----------------------------------------------------------------------------
# CTFTeam Model Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFTeamModel:
    """Tests for CTFTeam model."""

    def test_create_team(self, ctf_event_team):
        """Test creating a team."""
        team = CTFTeam.objects.create(
            event=ctf_event_team,
            name="Test Team",
        )

        assert team.id is not None
        assert team.invite_code is not None
        assert len(team.invite_code) > 16  # Should be secure token

    def test_team_str_representation(self, ctf_team):
        """Test team string representation."""
        assert str(ctf_team) == "Test Team"

    def test_team_member_count(self, ctf_team, ctf_participant_team):
        """Test member_count property."""
        assert ctf_team.member_count == 1

    def test_team_is_full(self, ctf_event_team, ctf_team, participant_user, second_participant_user):
        """Test is_full property."""
        # Team limit is 4, add 4 members
        for i in range(4):
            CTFParticipant.objects.create(
                event=ctf_event_team,
                email=f"member{i}@test.com",
                name=f"Member {i}",
                team=ctf_team,
                status=ParticipantStatus.ACTIVE.value,
            )

        assert ctf_team.is_full is True

    def test_team_unique_name_per_event(self, ctf_event_team, ctf_team):
        """Test unique constraint on team name per event."""
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            CTFTeam.objects.create(
                event=ctf_event_team,
                name=ctf_team.name,  # Same name
            )


# -----------------------------------------------------------------------------
# CTFParticipant Model Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFParticipantModel:
    """Tests for CTFParticipant model."""

    def test_create_participant(self, ctf_event):
        """Test creating a participant."""
        participant = CTFParticipant.objects.create(
            event=ctf_event,
            email="test@test.com",
            name="Test Person",
        )

        assert participant.id is not None
        assert participant.invite_token is not None
        assert participant.invite_token_expires is not None
        assert participant.status == ParticipantStatus.INVITED.value

    def test_participant_str_representation(self, ctf_participant):
        """Test participant string representation."""
        assert "Test Participant" in str(ctf_participant)
        assert "participant@test.com" in str(ctf_participant)

    def test_participant_is_registered(self, ctf_participant):
        """Test is_registered property."""
        assert ctf_participant.is_registered is True

    def test_participant_is_registered_false_when_invited(self, ctf_participant_invited):
        """Test is_registered for invited participant."""
        assert ctf_participant_invited.is_registered is False

    def test_participant_is_invite_valid(self, ctf_participant_invited):
        """Test is_invite_valid property."""
        assert ctf_participant_invited.is_invite_valid is True

    def test_participant_is_invite_expired(self, ctf_event):
        """Test is_invite_valid for expired token."""
        participant = CTFParticipant.objects.create(
            event=ctf_event,
            email="expired@test.com",
            name="Expired",
            invite_token_expires=timezone.now() - timedelta(hours=1),
        )
        assert participant.is_invite_valid is False

    def test_participant_total_score(self, ctf_participant, ctf_challenge, ctf_submission_correct):
        """Test total_score property."""
        assert ctf_participant.total_score == 100

    def test_participant_solved_challenge_count(self, ctf_participant, ctf_challenge, ctf_submission_correct):
        """Test solved_challenge_count property."""
        assert ctf_participant.solved_challenge_count == 1

    def test_participant_validation_team_in_non_team_event(self, ctf_event, ctf_event_team, ctf_team):
        """Test validation rejects team assignment in non-team event."""
        with pytest.raises(ValidationError) as exc_info:
            participant = CTFParticipant(
                event=ctf_event,  # Non-team event
                email="test@test.com",
                name="Test",
                team=ctf_team,  # But with team
            )
            participant.full_clean()

        assert "team" in exc_info.value.message_dict

    def test_participant_unique_email_per_event(self, ctf_event, ctf_participant):
        """Test unique constraint on email per event."""
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            CTFParticipant.objects.create(
                event=ctf_event,
                email=ctf_participant.email,  # Same email
                name="Another Person",
            )

    def test_participant_update_last_active(self, ctf_participant):
        """Test update_last_active method."""
        assert ctf_participant.last_active_at is None

        ctf_participant.update_last_active()

        assert ctf_participant.last_active_at is not None


# -----------------------------------------------------------------------------
# CTFSubmission Model Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFSubmissionModel:
    """Tests for CTFSubmission model."""

    def test_create_submission(self, ctf_participant, ctf_challenge):
        """Test creating a submission."""
        submission = CTFSubmission.objects.create(
            participant=ctf_participant,
            challenge=ctf_challenge,
            **create_submission_data(),
        )

        assert submission.id is not None
        assert submission.submitted_at is not None

    def test_submission_str_representation(self, ctf_submission_correct):
        """Test submission string representation."""
        assert "Test Participant" in str(ctf_submission_correct)
        assert "Test Challenge" in str(ctf_submission_correct)
        assert "correct" in str(ctf_submission_correct)

    def test_submission_validation_mismatched_event(self, ctf_event, ctf_event_draft, ctf_participant, organizer_user):
        """Test validation rejects challenge from different event."""
        other_challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,  # Different event
            name="Other Challenge",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="hash",
        )

        with pytest.raises(ValidationError) as exc_info:
            submission = CTFSubmission(
                participant=ctf_participant,
                challenge=other_challenge,
                submitted_flag="FLAG{test}",
            )
            submission.full_clean()

        assert "challenge" in exc_info.value.message_dict


# -----------------------------------------------------------------------------
# CTFScheduledTask Model Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCTFScheduledTaskModel:
    """Tests for CTFScheduledTask model."""

    def test_create_scheduled_task(self, ctf_event):
        """Test creating a scheduled task."""
        task = CTFScheduledTask.objects.create(
            event=ctf_event,
            task_type="spin_up_ranges",
            scheduled_for=timezone.now() + timedelta(hours=1),
        )

        assert task.id is not None
        assert task.status == ScheduledTaskStatus.PENDING.value

    def test_task_is_due_future(self, ctf_event):
        """Test is_due for future task."""
        task = CTFScheduledTask.objects.create(
            event=ctf_event,
            task_type="spin_up_ranges",
            scheduled_for=timezone.now() + timedelta(hours=1),
        )
        assert task.is_due is False

    def test_task_is_due_past(self, ctf_event):
        """Test is_due for past task."""
        task = CTFScheduledTask.objects.create(
            event=ctf_event,
            task_type="spin_up_ranges",
            scheduled_for=timezone.now() - timedelta(minutes=1),
        )
        assert task.is_due is True

    def test_task_mark_running(self, ctf_event):
        """Test mark_running method."""
        task = CTFScheduledTask.objects.create(
            event=ctf_event,
            task_type="spin_up_ranges",
            scheduled_for=timezone.now(),
        )

        task.mark_running()

        assert task.status == ScheduledTaskStatus.RUNNING.value

    def test_task_mark_completed(self, ctf_event):
        """Test mark_completed method."""
        task = CTFScheduledTask.objects.create(
            event=ctf_event,
            task_type="spin_up_ranges",
            scheduled_for=timezone.now(),
        )

        task.mark_completed()

        assert task.status == ScheduledTaskStatus.COMPLETED.value
        assert task.executed_at is not None

    def test_task_mark_failed(self, ctf_event):
        """Test mark_failed method."""
        task = CTFScheduledTask.objects.create(
            event=ctf_event,
            task_type="spin_up_ranges",
            scheduled_for=timezone.now(),
        )

        task.mark_failed("Connection timeout")

        assert task.status == ScheduledTaskStatus.FAILED.value
        assert task.error_message == "Connection timeout"
        assert task.executed_at is not None

    def test_task_mark_cancelled(self, ctf_event):
        """Test mark_cancelled method."""
        task = CTFScheduledTask.objects.create(
            event=ctf_event,
            task_type="spin_up_ranges",
            scheduled_for=timezone.now(),
        )

        task.mark_cancelled()

        assert task.status == ScheduledTaskStatus.CANCELLED.value
