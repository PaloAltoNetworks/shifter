"""Tests for CTF models.

Following TDD approach - these tests define expected model behavior.
Uses in-memory model construction and mocks instead of database access.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

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

# -----------------------------------------------------------------------------
# CTFEvent Model Tests
# -----------------------------------------------------------------------------


class TestCTFEventModel:
    """Tests for CTFEvent model."""

    def _make_event(self, **overrides):
        """Build an in-memory CTFEvent without saving.

        Uses `created_by_id` to avoid Django FK descriptor validation.
        """
        now = timezone.now()
        defaults = {
            "id": uuid4(),
            "name": "Test CTF Event",
            "created_by_id": 1,
            "status": EventStatus.SCHEDULED.value,
            "event_start": now + timedelta(days=1),
            "event_end": now + timedelta(days=1, hours=8),
            "scenario_id": "basic",
            "auto_cleanup": True,
            "cleanup_delay_hours": 24,
            "team_mode": False,
            "range_spinup_minutes": 30,
        }
        defaults.update(overrides)
        return CTFEvent(**defaults)

    def test_create_event_defaults(self):
        """Test that a freshly constructed event has expected defaults."""
        now = timezone.now()
        event = CTFEvent(
            name="Test Event",
            created_by_id=1,
            event_start=now + timedelta(days=1),
            event_end=now + timedelta(days=1, hours=8),
        )

        assert event.name == "Test Event"
        assert event.status == EventStatus.DRAFT.value
        assert event.auto_cleanup is True
        assert event.cleanup_delay_hours == 24
        assert event.scenario_id == "basic"

    def test_event_str_representation(self):
        """Test event string representation."""
        event = self._make_event(name="Test CTF Event")
        assert str(event) == "Test CTF Event"

    def test_event_is_active_property(self):
        """Test is_active property for active event."""
        event = self._make_event(status=EventStatus.ACTIVE.value)
        assert event.is_active is True

    def test_event_is_active_false_for_draft(self):
        """Test is_active property for draft event."""
        event = self._make_event(status=EventStatus.DRAFT.value)
        assert event.is_active is False

    def test_event_is_upcoming_property(self):
        """Test is_upcoming property for scheduled event with future start."""
        event = self._make_event(
            status=EventStatus.SCHEDULED.value,
            event_start=timezone.now() + timedelta(days=1),
        )
        assert event.is_upcoming is True

    def test_event_is_modifiable_for_draft(self):
        """Test is_modifiable for draft event."""
        event = self._make_event(status=EventStatus.DRAFT.value)
        assert event.is_modifiable is True

    def test_event_is_modifiable_for_completed(self):
        """Test is_modifiable for completed event."""
        event = self._make_event(status=EventStatus.COMPLETED.value)
        assert event.is_modifiable is False

    def test_event_duration_hours(self):
        """Test duration_hours calculation."""
        now = timezone.now()
        event = self._make_event(
            event_start=now,
            event_end=now + timedelta(hours=8),
        )
        assert event.duration_hours == pytest.approx(8.0)

    def test_event_participant_count(self):
        """Test participant_count property uses queryset count."""
        event = self._make_event()
        mock_qs = MagicMock()
        mock_qs.count.return_value = 3
        with patch.object(type(event), "participants", new_callable=lambda: property(lambda self: mock_qs)):
            assert event.participant_count == 3

    def test_event_challenge_count(self):
        """Test challenge_count property uses queryset count."""
        event = self._make_event()
        mock_qs = MagicMock()
        mock_qs.count.return_value = 5
        with patch.object(type(event), "challenges", new_callable=lambda: property(lambda self: mock_qs)):
            assert event.challenge_count == 5

    def test_event_get_cleanup_time(self):
        """Test get_cleanup_time calculation."""
        now = timezone.now()
        event = self._make_event(
            event_end=now + timedelta(hours=8),
            cleanup_delay_hours=24,
        )
        expected = event.event_end + timedelta(hours=24)
        assert event.get_cleanup_time() == expected

    def test_event_get_spinup_time(self):
        """Test get_spinup_time calculation."""
        now = timezone.now()
        event = self._make_event(
            event_start=now + timedelta(days=1),
            range_spinup_minutes=30,
        )
        expected = event.event_start - timedelta(minutes=30)
        assert event.get_spinup_time() == expected

    def test_event_validation_end_before_start_fails(self):
        """Test validation rejects end time before start time."""
        now = timezone.now()
        event = CTFEvent(
            name="Invalid Event",
            created_by_id=1,
            event_start=now + timedelta(days=2),
            event_end=now + timedelta(days=1),
        )
        with pytest.raises(ValidationError) as exc_info:
            event.clean()

        assert "event_end" in exc_info.value.message_dict

    def test_event_validation_team_mode_requires_size_limit(self):
        """Test validation requires team_size_limit when team_mode is True."""
        now = timezone.now()
        event = CTFEvent(
            name="Team Event",
            created_by_id=1,
            event_start=now + timedelta(days=1),
            event_end=now + timedelta(days=1, hours=8),
            team_mode=True,
            team_size_limit=None,
        )
        with pytest.raises(ValidationError) as exc_info:
            event.clean()

        assert "team_size_limit" in exc_info.value.message_dict

    def test_event_soft_delete(self):
        """Test soft delete sets deleted_at and calls save."""
        event = self._make_event()
        assert event.deleted_at is None

        with patch.object(CTFEvent, "save") as mock_save:
            event.delete(soft=True)

        assert event.deleted_at is not None
        assert event.is_deleted is True
        mock_save.assert_called_once()

    def test_event_restore(self):
        """Test restoring a soft-deleted event."""
        event = self._make_event()
        event.deleted_at = timezone.now()
        assert event.is_deleted is True

        with patch.object(CTFEvent, "save"):
            event.restore()

        assert event.deleted_at is None
        assert event.is_deleted is False


# -----------------------------------------------------------------------------
# CTFChallenge Model Tests
# -----------------------------------------------------------------------------


class TestCTFChallengeModel:
    """Tests for CTFChallenge model."""

    def _make_event(self, **overrides):
        """Build an in-memory CTFEvent."""
        now = timezone.now()
        defaults = {
            "id": uuid4(),
            "name": "Test Event",
            "created_by_id": 1,
            "status": EventStatus.SCHEDULED.value,
            "event_start": now + timedelta(days=1),
            "event_end": now + timedelta(days=1, hours=8),
            "team_mode": False,
        }
        defaults.update(overrides)
        return CTFEvent(**defaults)

    def _make_challenge(self, event=None, **overrides):
        """Build an in-memory CTFChallenge."""
        if event is None:
            event = self._make_event()
        defaults = {
            "id": uuid4(),
            "event": event,
            "name": "Test Challenge",
            "description": "Find the flag in the source code",
            "category": ChallengeCategory.WEB.value,
            "points": 100,
            "difficulty": ChallengeDifficulty.EASY.value,
            "flag_hash": "$2b$12$test_hash_placeholder",
            "flag_format": "FLAG{...}",
            "hint": "",
            "hint_penalty": 0,
            "release_time": None,
            "order": 0,
        }
        defaults.update(overrides)
        return CTFChallenge(**defaults)

    def test_challenge_str_representation(self):
        """Test challenge string representation."""
        challenge = self._make_challenge(
            category=ChallengeCategory.WEB.value,
            name="Test Challenge",
        )
        assert str(challenge) == "[web] Test Challenge"

    def test_challenge_is_released_no_release_time(self):
        """Test is_released when no release_time set."""
        challenge = self._make_challenge(release_time=None)
        assert challenge.is_released is True

    def test_challenge_is_released_future_time(self):
        """Test is_released for future release time."""
        challenge = self._make_challenge(
            release_time=timezone.now() + timedelta(hours=2),
        )
        assert challenge.is_released is False

    def test_challenge_solve_count(self):
        """Test solve_count property uses queryset."""
        challenge = self._make_challenge()
        mock_submissions = MagicMock()
        mock_submissions.filter.return_value.count.return_value = 3
        with patch.object(type(challenge), "submissions", new_callable=lambda: property(lambda self: mock_submissions)):
            assert challenge.solve_count == 3
        mock_submissions.filter.assert_called_once_with(is_correct=True)

    def test_challenge_first_blood(self):
        """Test first_blood property uses queryset."""
        challenge = self._make_challenge()
        mock_submission = Mock()
        mock_submissions = MagicMock()
        mock_submissions.filter.return_value.order_by.return_value.first.return_value = mock_submission
        with patch.object(type(challenge), "submissions", new_callable=lambda: property(lambda self: mock_submissions)):
            assert challenge.first_blood == mock_submission
        mock_submissions.filter.assert_called_once_with(is_correct=True)

    def test_challenge_calculate_points_no_penalty(self):
        """Test points calculation without hint penalty."""
        challenge = self._make_challenge(points=100, hint_penalty=0)
        points = challenge.calculate_points_with_penalty(hint_used=False)
        assert points == 100

    def test_challenge_calculate_points_with_penalty(self):
        """Test points calculation with hint penalty."""
        challenge = self._make_challenge(
            points=200,
            hint="Look at the cipher mode",
            hint_penalty=25,
        )
        # 25% of 200 = 50, so 200 - 50 = 150
        points = challenge.calculate_points_with_penalty(hint_used=True)
        assert points == 150

    def test_challenge_validation_hint_penalty_without_hint(self):
        """Test validation rejects hint_penalty without hint."""
        challenge = self._make_challenge(
            hint="",  # No hint
            hint_penalty=25,  # But penalty set
        )
        with pytest.raises(ValidationError) as exc_info:
            challenge.clean()

        assert "hint_penalty" in exc_info.value.message_dict


# -----------------------------------------------------------------------------
# CTFTeam Model Tests
# -----------------------------------------------------------------------------


class TestCTFTeamModel:
    """Tests for CTFTeam model."""

    def _make_event(self, **overrides):
        """Build an in-memory CTFEvent."""
        now = timezone.now()
        defaults = {
            "id": uuid4(),
            "name": "Team CTF Event",
            "created_by_id": 1,
            "status": EventStatus.SCHEDULED.value,
            "event_start": now + timedelta(days=1),
            "event_end": now + timedelta(days=1, hours=8),
            "team_mode": True,
            "team_size_limit": 4,
        }
        defaults.update(overrides)
        return CTFEvent(**defaults)

    def _make_team(self, event=None, **overrides):
        """Build an in-memory CTFTeam."""
        if event is None:
            event = self._make_event()
        defaults = {
            "id": uuid4(),
            "event": event,
            "name": "Test Team",
            "invite_code": "test-invite-code-12345678",
        }
        defaults.update(overrides)
        return CTFTeam(**defaults)

    def test_team_str_representation(self):
        """Test team string representation."""
        team = self._make_team(name="Test Team")
        assert str(team) == "Test Team"

    def test_team_member_count(self):
        """Test member_count property uses queryset."""
        team = self._make_team()
        mock_members = MagicMock()
        mock_members.count.return_value = 3
        with patch.object(type(team), "members", new_callable=lambda: property(lambda self: mock_members)):
            assert team.member_count == 3

    def test_team_is_full_when_at_capacity(self):
        """Test is_full property when team is at capacity."""
        event = self._make_event(team_size_limit=4)
        team = self._make_team(event=event)
        mock_members = MagicMock()
        mock_members.count.return_value = 4
        with patch.object(type(team), "members", new_callable=lambda: property(lambda self: mock_members)):
            assert team.is_full is True

    def test_team_is_full_when_not_at_capacity(self):
        """Test is_full property when team has space."""
        event = self._make_event(team_size_limit=4)
        team = self._make_team(event=event)
        mock_members = MagicMock()
        mock_members.count.return_value = 2
        with patch.object(type(team), "members", new_callable=lambda: property(lambda self: mock_members)):
            assert team.is_full is False

    def test_team_is_full_no_limit(self):
        """Test is_full when no team_size_limit is set."""
        event = self._make_event(team_size_limit=None, team_mode=False)
        team = self._make_team(event=event)
        assert team.is_full is False


# -----------------------------------------------------------------------------
# CTFParticipant Model Tests
# -----------------------------------------------------------------------------


class TestCTFParticipantModel:
    """Tests for CTFParticipant model."""

    def _make_event(self, **overrides):
        """Build an in-memory CTFEvent."""
        now = timezone.now()
        defaults = {
            "id": uuid4(),
            "name": "Test CTF Event",
            "created_by_id": 1,
            "status": EventStatus.SCHEDULED.value,
            "event_start": now + timedelta(days=1),
            "event_end": now + timedelta(days=1, hours=8),
            "team_mode": False,
        }
        defaults.update(overrides)
        return CTFEvent(**defaults)

    def _make_participant(self, event=None, **overrides):
        """Build an in-memory CTFParticipant.

        Uses `user_id` to avoid Django FK descriptor validation.
        """
        if event is None:
            event = self._make_event()
        defaults = {
            "id": uuid4(),
            "event": event,
            "email": "participant@test.com",
            "name": "Test Participant",
            "user_id": 1,
            "status": ParticipantStatus.ACTIVE.value,
            "registered_at": timezone.now(),
            "invite_token": "test-token-abcdef123456",
            "invite_token_expires": timezone.now() + timedelta(days=7),
            "last_active_at": None,
        }
        defaults.update(overrides)
        return CTFParticipant(**defaults)

    def test_participant_str_representation(self):
        """Test participant string representation."""
        p = self._make_participant(name="Test Participant", email="participant@test.com")
        assert "Test Participant" in str(p)
        assert "participant@test.com" in str(p)

    def test_participant_is_registered(self):
        """Test is_registered property when user and registered_at are set."""
        from django.contrib.auth import get_user_model

        User = get_user_model()

        p = self._make_participant(user_id=1, registered_at=timezone.now())
        # is_registered checks self.user is not None — with user_id set but
        # no DB, accessing .user raises. Patch the descriptor to return a mock.
        mock_user = MagicMock(spec=User)
        with patch.object(CTFParticipant, "user", new_callable=lambda: property(lambda self: mock_user)):
            assert p.is_registered is True

    def test_participant_is_registered_false_when_invited(self):
        """Test is_registered for invited participant (no user)."""
        p = self._make_participant(
            user_id=None,
            registered_at=None,
            status=ParticipantStatus.INVITED.value,
        )
        assert p.is_registered is False

    def test_participant_is_invite_valid(self):
        """Test is_invite_valid property."""
        p = self._make_participant(
            invite_token_expires=timezone.now() + timedelta(days=7),
        )
        assert p.is_invite_valid is True

    def test_participant_is_invite_expired(self):
        """Test is_invite_valid for expired token."""
        p = self._make_participant(
            invite_token_expires=timezone.now() - timedelta(hours=1),
        )
        assert p.is_invite_valid is False

    def test_participant_total_score(self):
        """Test total_score property uses queryset."""
        p = self._make_participant()
        mock_submissions = MagicMock()
        mock_submissions.filter.return_value.aggregate.return_value = {"total": 250}
        with patch.object(type(p), "submissions", new_callable=lambda: property(lambda self: mock_submissions)):
            assert p.total_score == 250
        mock_submissions.filter.assert_called_once_with(is_correct=True)

    def test_participant_total_score_none_returns_zero(self):
        """Test total_score returns 0 when aggregate is None."""
        p = self._make_participant()
        mock_submissions = MagicMock()
        mock_submissions.filter.return_value.aggregate.return_value = {"total": None}
        with patch.object(type(p), "submissions", new_callable=lambda: property(lambda self: mock_submissions)):
            assert p.total_score == 0

    def test_participant_solved_challenge_count(self):
        """Test solved_challenge_count property uses queryset."""
        p = self._make_participant()
        mock_submissions = MagicMock()
        mock_submissions.filter.return_value.count.return_value = 5
        with patch.object(type(p), "submissions", new_callable=lambda: property(lambda self: mock_submissions)):
            assert p.solved_challenge_count == 5
        mock_submissions.filter.assert_called_once_with(is_correct=True)

    def test_participant_validation_team_in_non_team_event(self):
        """Test validation rejects team assignment in non-team event."""
        event = self._make_event(team_mode=False)
        team_event = self._make_event(team_mode=True, team_size_limit=4)
        team = CTFTeam(
            id=uuid4(),
            event=team_event,
            name="Test Team",
            invite_code="test-code-123",
        )
        # Participant's event is non-team, but has a team assigned
        p = self._make_participant(event=event, team=team)

        with pytest.raises(ValidationError) as exc_info:
            p.clean()

        assert "team" in exc_info.value.message_dict

    def test_participant_update_last_active(self):
        """Test update_last_active method sets timestamp and calls save."""
        p = self._make_participant(last_active_at=None)
        assert p.last_active_at is None

        with patch.object(CTFParticipant, "save") as mock_save:
            p.update_last_active()

        assert p.last_active_at is not None
        mock_save.assert_called_once_with(update_fields=["last_active_at", "updated_at"])


# -----------------------------------------------------------------------------
# CTFSubmission Model Tests
# -----------------------------------------------------------------------------


class TestCTFSubmissionModel:
    """Tests for CTFSubmission model."""

    def _make_event(self, **overrides):
        """Build an in-memory CTFEvent."""
        now = timezone.now()
        defaults = {
            "id": uuid4(),
            "name": "Test Event",
            "created_by_id": 1,
            "event_start": now + timedelta(days=1),
            "event_end": now + timedelta(days=1, hours=8),
        }
        defaults.update(overrides)
        return CTFEvent(**defaults)

    def test_submission_str_representation(self):
        """Test submission string representation."""
        event = self._make_event()
        participant = CTFParticipant(
            id=uuid4(),
            event=event,
            email="test@test.com",
            name="Test Participant",
            invite_token="tok",
            invite_token_expires=timezone.now() + timedelta(days=1),
        )
        challenge = CTFChallenge(
            id=uuid4(),
            event=event,
            name="Test Challenge",
            description="desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="hash",
        )
        submission = CTFSubmission(
            id=uuid4(),
            participant=participant,
            challenge=challenge,
            submitted_flag="FLAG{correct}",
            is_correct=True,
            points_awarded=100,
        )

        result = str(submission)
        assert "Test Participant" in result
        assert "Test Challenge" in result
        assert "correct" in result

    def test_submission_validation_mismatched_event(self):
        """Test validation rejects challenge from different event."""
        event1 = self._make_event()
        event2 = self._make_event()
        participant = CTFParticipant(
            id=uuid4(),
            event=event1,
            email="test@test.com",
            name="Test",
            invite_token="tok",
            invite_token_expires=timezone.now() + timedelta(days=1),
        )
        challenge = CTFChallenge(
            id=uuid4(),
            event=event2,  # Different event
            name="Other Challenge",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="hash",
        )
        submission = CTFSubmission(
            id=uuid4(),
            participant=participant,
            challenge=challenge,
            submitted_flag="FLAG{test}",
        )

        with pytest.raises(ValidationError) as exc_info:
            submission.clean()

        assert "challenge" in exc_info.value.message_dict


# -----------------------------------------------------------------------------
# CTFScheduledTask Model Tests
# -----------------------------------------------------------------------------


class TestCTFScheduledTaskModel:
    """Tests for CTFScheduledTask model."""

    def _make_event(self, **overrides):
        """Build an in-memory CTFEvent for FK reference."""
        defaults = {
            "id": uuid4(),
            "name": "Test Event",
            "created_by_id": 1,
            "event_start": timezone.now() + timedelta(days=1),
            "event_end": timezone.now() + timedelta(days=1, hours=8),
        }
        defaults.update(overrides)
        return CTFEvent(**defaults)

    def _make_task(self, event=None, **overrides):
        """Build an in-memory CTFScheduledTask."""
        if event is None:
            event = self._make_event()
        defaults = {
            "id": uuid4(),
            "event": event,
            "task_type": "spin_up_ranges",
            "scheduled_for": timezone.now() + timedelta(hours=1),
            "status": ScheduledTaskStatus.PENDING.value,
            "error_message": "",
            "executed_at": None,
        }
        defaults.update(overrides)
        return CTFScheduledTask(**defaults)

    def test_task_default_status(self):
        """Test default status is PENDING."""
        task = self._make_task()
        assert task.status == ScheduledTaskStatus.PENDING.value

    def test_task_is_due_future(self):
        """Test is_due for future task."""
        task = self._make_task(
            scheduled_for=timezone.now() + timedelta(hours=1),
            status=ScheduledTaskStatus.PENDING.value,
        )
        assert task.is_due is False

    def test_task_is_due_past(self):
        """Test is_due for past task."""
        task = self._make_task(
            scheduled_for=timezone.now() - timedelta(minutes=1),
            status=ScheduledTaskStatus.PENDING.value,
        )
        assert task.is_due is True

    def test_task_mark_running(self):
        """Test mark_running method."""
        task = self._make_task()

        with patch.object(CTFScheduledTask, "save"):
            task.mark_running()

        assert task.status == ScheduledTaskStatus.RUNNING.value

    def test_task_mark_completed(self):
        """Test mark_completed method."""
        task = self._make_task()

        with patch.object(CTFScheduledTask, "save"):
            task.mark_completed()

        assert task.status == ScheduledTaskStatus.COMPLETED.value
        assert task.executed_at is not None

    def test_task_mark_failed(self):
        """Test mark_failed method."""
        task = self._make_task()

        with patch.object(CTFScheduledTask, "save"):
            task.mark_failed("Connection timeout")

        assert task.status == ScheduledTaskStatus.FAILED.value
        assert task.error_message == "Connection timeout"
        assert task.executed_at is not None

    def test_task_mark_cancelled(self):
        """Test mark_cancelled method."""
        task = self._make_task()

        with patch.object(CTFScheduledTask, "save"):
            task.mark_cancelled()

        assert task.status == ScheduledTaskStatus.CANCELLED.value
