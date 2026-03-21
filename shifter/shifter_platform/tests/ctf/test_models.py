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

from .conftest import (
    make_challenge,
    make_ctf_event,
    make_participant,
    make_scheduled_task,
    make_team,
)

# -----------------------------------------------------------------------------
# CTFEvent Model Tests
# -----------------------------------------------------------------------------


class TestCTFEventModel:
    """Tests for CTFEvent model."""

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
        event = make_ctf_event(name="Test CTF Event")
        assert str(event) == "Test CTF Event"

    @pytest.mark.parametrize(
        "status,expected",
        [
            pytest.param(EventStatus.ACTIVE.value, True, id="active"),
            pytest.param(EventStatus.DRAFT.value, False, id="draft"),
            pytest.param(EventStatus.SCHEDULED.value, False, id="scheduled"),
            pytest.param(EventStatus.COMPLETED.value, False, id="completed"),
        ],
    )
    def test_event_is_active_property(self, status, expected):
        """Test is_active property for various statuses."""
        event = make_ctf_event(status=status)
        assert event.is_active is expected

    def test_event_is_upcoming_property(self):
        """Test is_upcoming property for scheduled event with future start."""
        event = make_ctf_event(
            status=EventStatus.SCHEDULED.value,
            event_start=timezone.now() + timedelta(days=1),
        )
        assert event.is_upcoming is True

    @pytest.mark.parametrize(
        "status,expected",
        [
            pytest.param(EventStatus.DRAFT.value, True, id="draft"),
            pytest.param(EventStatus.SCHEDULED.value, True, id="scheduled"),
            pytest.param(EventStatus.COMPLETED.value, False, id="completed"),
        ],
    )
    def test_event_is_modifiable(self, status, expected):
        """Test is_modifiable for various statuses."""
        event = make_ctf_event(status=status)
        assert event.is_modifiable is expected

    def test_event_duration_hours(self):
        """Test duration_hours calculation."""
        now = timezone.now()
        event = make_ctf_event(
            event_start=now,
            event_end=now + timedelta(hours=8),
        )
        assert event.duration_hours == pytest.approx(8.0)

    @pytest.mark.parametrize(
        "relation,property_name,count",
        [
            pytest.param("participants", "participant_count", 3, id="participants"),
            pytest.param("challenges", "challenge_count", 5, id="challenges"),
        ],
    )
    def test_event_count_properties(self, relation, property_name, count):
        """Test count properties use queryset count."""
        event = make_ctf_event()
        mock_qs = MagicMock()
        mock_qs.count.return_value = count
        with patch.object(type(event), relation, new_callable=lambda: property(lambda self: mock_qs)):
            assert getattr(event, property_name) == count

    def test_event_get_cleanup_time(self):
        """Test get_cleanup_time calculation."""
        now = timezone.now()
        event = make_ctf_event(
            event_end=now + timedelta(hours=8),
            cleanup_delay_hours=24,
        )
        expected = event.event_end + timedelta(hours=24)
        assert event.get_cleanup_time() == expected

    def test_event_get_spinup_time(self):
        """Test get_spinup_time calculation."""
        now = timezone.now()
        event = make_ctf_event(
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
        event = make_ctf_event()
        assert event.deleted_at is None

        with patch.object(CTFEvent, "save") as mock_save:
            event.delete(soft=True)

        assert event.deleted_at is not None
        assert event.is_deleted is True
        mock_save.assert_called_once()

    def test_event_restore(self):
        """Test restoring a soft-deleted event."""
        event = make_ctf_event()
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

    def test_challenge_str_representation(self):
        """Test challenge string representation."""
        challenge = make_challenge(
            category=ChallengeCategory.WEB.value,
            name="Test Challenge",
        )
        assert str(challenge) == "[web] Test Challenge"

    @pytest.mark.parametrize(
        "release_time_offset,expected",
        [
            pytest.param(None, True, id="no-release-time"),
            pytest.param(timedelta(hours=2), False, id="future-release"),
            pytest.param(timedelta(hours=-1), True, id="past-release"),
        ],
    )
    def test_challenge_is_released(self, release_time_offset, expected):
        """Test is_released for various release times."""
        release_time = None if release_time_offset is None else timezone.now() + release_time_offset
        challenge = make_challenge(release_time=release_time)
        assert challenge.is_released is expected

    def test_challenge_solve_count(self):
        """Test solve_count property uses queryset."""
        challenge = make_challenge()
        mock_submissions = MagicMock()
        mock_submissions.filter.return_value.count.return_value = 3
        with patch.object(type(challenge), "submissions", new_callable=lambda: property(lambda self: mock_submissions)):
            assert challenge.solve_count == 3
        mock_submissions.filter.assert_called_once_with(is_correct=True)

    def test_challenge_first_blood(self):
        """Test first_blood property uses queryset."""
        challenge = make_challenge()
        mock_submission = Mock()
        mock_submissions = MagicMock()
        mock_submissions.filter.return_value.order_by.return_value.first.return_value = mock_submission
        with patch.object(type(challenge), "submissions", new_callable=lambda: property(lambda self: mock_submissions)):
            assert challenge.first_blood == mock_submission
        mock_submissions.filter.assert_called_once_with(is_correct=True)

    @pytest.mark.parametrize(
        "points,hint_penalty,hint_used,expected",
        [
            pytest.param(100, 0, False, 100, id="no-penalty"),
            pytest.param(200, 25, True, 150, id="with-penalty"),
            pytest.param(200, 25, False, 200, id="penalty-not-used"),
        ],
    )
    def test_challenge_calculate_points(self, points, hint_penalty, hint_used, expected):
        """Test points calculation with various penalty configurations."""
        challenge = make_challenge(
            points=points,
            hint="Look at the cipher mode" if hint_penalty else "",
            hint_penalty=hint_penalty,
        )
        assert challenge.calculate_points_with_penalty(hint_used=hint_used) == expected

    def test_challenge_validation_hint_penalty_without_hint(self):
        """Test validation rejects hint_penalty without hint."""
        challenge = make_challenge(hint="", hint_penalty=25)
        with pytest.raises(ValidationError) as exc_info:
            challenge.clean()

        assert "hint_penalty" in exc_info.value.message_dict


# -----------------------------------------------------------------------------
# CTFTeam Model Tests
# -----------------------------------------------------------------------------


class TestCTFTeamModel:
    """Tests for CTFTeam model."""

    def test_team_str_representation(self):
        """Test team string representation."""
        team = make_team(name="Test Team")
        assert str(team) == "Test Team"

    def test_team_member_count(self):
        """Test member_count property uses queryset."""
        team = make_team()
        mock_members = MagicMock()
        mock_members.count.return_value = 3
        with patch.object(type(team), "members", new_callable=lambda: property(lambda self: mock_members)):
            assert team.member_count == 3

    @pytest.mark.parametrize(
        "team_size_limit,member_count,expected",
        [
            pytest.param(4, 4, True, id="at-capacity"),
            pytest.param(4, 2, False, id="has-space"),
        ],
    )
    def test_team_is_full(self, team_size_limit, member_count, expected):
        """Test is_full property for various capacities."""
        event = make_ctf_event(team_mode=True, team_size_limit=team_size_limit)
        team = make_team(event=event)
        mock_members = MagicMock()
        mock_members.count.return_value = member_count
        with patch.object(type(team), "members", new_callable=lambda: property(lambda self: mock_members)):
            assert team.is_full is expected

    def test_team_is_full_no_limit(self):
        """Test is_full when no team_size_limit is set."""
        event = make_ctf_event(team_size_limit=None, team_mode=False)
        team = make_team(event=event)
        assert team.is_full is False


# -----------------------------------------------------------------------------
# CTFParticipant Model Tests
# -----------------------------------------------------------------------------


class TestCTFParticipantModel:
    """Tests for CTFParticipant model."""

    def test_participant_str_representation(self):
        """Test participant string representation."""
        p = make_participant(name="Test Participant", email="participant@test.com")
        assert "Test Participant" in str(p)
        assert "participant@test.com" in str(p)

    def test_participant_is_registered(self):
        """Test is_registered property when user and registered_at are set."""
        from django.contrib.auth import get_user_model

        User = get_user_model()

        p = make_participant(user_id=1, registered_at=timezone.now())
        mock_user = MagicMock(spec=User)
        with patch.object(CTFParticipant, "user", new_callable=lambda: property(lambda self: mock_user)):
            assert p.is_registered is True

    def test_participant_is_registered_false_when_invited(self):
        """Test is_registered for invited participant (no user)."""
        p = make_participant(
            user_id=None,
            registered_at=None,
            status=ParticipantStatus.INVITED.value,
        )
        assert p.is_registered is False

    @pytest.mark.parametrize(
        "expires_offset,expected",
        [
            pytest.param(timedelta(days=7), True, id="valid"),
            pytest.param(timedelta(hours=-1), False, id="expired"),
        ],
    )
    def test_participant_is_invite_valid(self, expires_offset, expected):
        """Test is_invite_valid for various token expiry times."""
        p = make_participant(invite_token_expires=timezone.now() + expires_offset)
        assert p.is_invite_valid is expected

    @pytest.mark.parametrize(
        "aggregate_total,expected",
        [
            pytest.param(250, 250, id="has-score"),
            pytest.param(None, 0, id="none-returns-zero"),
            pytest.param(0, 0, id="zero-score"),
        ],
    )
    def test_participant_total_score(self, aggregate_total, expected):
        """Test total_score property with various aggregate results."""
        p = make_participant()
        mock_submissions = MagicMock()
        mock_submissions.filter.return_value.aggregate.return_value = {"total": aggregate_total}
        with patch.object(type(p), "submissions", new_callable=lambda: property(lambda self: mock_submissions)):
            assert p.total_score == expected
        mock_submissions.filter.assert_called_once_with(is_correct=True)

    def test_participant_solved_challenge_count(self):
        """Test solved_challenge_count property uses queryset."""
        p = make_participant()
        mock_submissions = MagicMock()
        mock_submissions.filter.return_value.count.return_value = 5
        with patch.object(type(p), "submissions", new_callable=lambda: property(lambda self: mock_submissions)):
            assert p.solved_challenge_count == 5
        mock_submissions.filter.assert_called_once_with(is_correct=True)

    def test_participant_validation_team_in_non_team_event(self):
        """Test validation rejects team assignment in non-team event."""
        event = make_ctf_event(team_mode=False)
        team_event = make_ctf_event(team_mode=True, team_size_limit=4)
        team = CTFTeam(
            id=uuid4(),
            event=team_event,
            name="Test Team",
            invite_code="test-code-123",
        )
        p = make_participant(event=event, team=team)

        with pytest.raises(ValidationError) as exc_info:
            p.clean()

        assert "team" in exc_info.value.message_dict

    def test_participant_update_last_active(self):
        """Test update_last_active method sets timestamp and calls save."""
        p = make_participant(last_active_at=None)
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

    def test_submission_str_representation(self):
        """Test submission string representation."""
        event = make_ctf_event()
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
        event1 = make_ctf_event()
        event2 = make_ctf_event()
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

    def test_task_default_status(self):
        """Test default status is PENDING."""
        task = make_scheduled_task()
        assert task.status == ScheduledTaskStatus.PENDING.value

    @pytest.mark.parametrize(
        "scheduled_offset,expected",
        [
            pytest.param(timedelta(hours=1), False, id="future"),
            pytest.param(timedelta(minutes=-1), True, id="past"),
        ],
    )
    def test_task_is_due(self, scheduled_offset, expected):
        """Test is_due for various schedule times."""
        task = make_scheduled_task(
            scheduled_for=timezone.now() + scheduled_offset,
            status=ScheduledTaskStatus.PENDING.value,
        )
        assert task.is_due is expected

    @pytest.mark.parametrize(
        "method,expected_status,has_executed_at",
        [
            pytest.param("mark_running", ScheduledTaskStatus.RUNNING.value, False, id="running"),
            pytest.param("mark_completed", ScheduledTaskStatus.COMPLETED.value, True, id="completed"),
            pytest.param("mark_cancelled", ScheduledTaskStatus.CANCELLED.value, False, id="cancelled"),
        ],
    )
    def test_task_status_transitions(self, method, expected_status, has_executed_at):
        """Test status transition methods."""
        task = make_scheduled_task()

        with patch.object(CTFScheduledTask, "save"):
            getattr(task, method)()

        assert task.status == expected_status
        if has_executed_at:
            assert task.executed_at is not None

    def test_task_mark_failed(self):
        """Test mark_failed method sets error message."""
        task = make_scheduled_task()

        with patch.object(CTFScheduledTask, "save"):
            task.mark_failed("Connection timeout")

        assert task.status == ScheduledTaskStatus.FAILED.value
        assert task.error_message == "Connection timeout"
        assert task.executed_at is not None
