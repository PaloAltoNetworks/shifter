"""Tests for CTF Submission service — rate limiting and attempt limits.

Integration-style tests using real DB objects. Only verify_flag is mocked
since it requires bcrypt hashes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from ctf.enums import (
    ChallengeCategory,
    ChallengeDifficulty,
    EventStatus,
    ParticipantStatus,
)
from ctf.exceptions import CTFRateLimitError, CTFStateError
from ctf.models import CTFChallenge, CTFEvent, CTFParticipant, CTFSubmission
from ctf.services.submission import submit_flag


@pytest.fixture
def active_event(db, organizer_user):
    """Active event with submission cooldown enabled."""
    return CTFEvent.objects.create(
        name="Rate Limit Test Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
        submission_cooldown_seconds=10,
    )


@pytest.fixture
def active_event_no_cooldown(db, organizer_user):
    """Active event with no submission cooldown."""
    return CTFEvent.objects.create(
        name="No Cooldown Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
        submission_cooldown_seconds=0,
    )


@pytest.fixture
def challenge(db, active_event):
    """Challenge in the rate-limited event."""
    return CTFChallenge.objects.create(
        event=active_event,
        name="Rate Limit Challenge",
        description="Test challenge",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$placeholder",
        flag_format="FLAG{...}",
    )


@pytest.fixture
def challenge_b(db, active_event):
    """Second challenge in the same event."""
    return CTFChallenge.objects.create(
        event=active_event,
        name="Second Challenge",
        description="Another test challenge",
        category=ChallengeCategory.CRYPTO.value,
        points=200,
        difficulty=ChallengeDifficulty.MEDIUM.value,
        flag_hash="$2b$12$placeholder2",
        flag_format="FLAG{...}",
    )


@pytest.fixture
def participant(db, active_event, participant_user):
    """Active participant in the rate-limited event."""
    return CTFParticipant.objects.create(
        event=active_event,
        user=participant_user,
        email=participant_user.email,
        name="Rate Limit Participant",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


@pytest.mark.django_db
class TestSubmissionRateLimit:
    """Tests for time-based submission rate limiting (CTF-114)."""

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_rate_limited_within_cooldown(self, mock_verify, participant, challenge):
        """Submission within cooldown window raises CTFRateLimitError."""
        # First submission succeeds
        submit_flag(participant.id, challenge.id, "FLAG{wrong}")

        # Second submission within cooldown is rejected
        with pytest.raises(CTFRateLimitError) as exc_info:
            submit_flag(participant.id, challenge.id, "FLAG{wrong2}")

        assert "retry_after_seconds" in exc_info.value.details
        assert exc_info.value.details["cooldown_seconds"] == 10

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_rate_limit_allows_after_cooldown(self, mock_verify, participant, challenge):
        """Submission after cooldown window succeeds."""
        # Create a submission, then backdate it past the cooldown window
        # (auto_now_add prevents setting submitted_at in create())
        old_sub = CTFSubmission.objects.create(
            participant=participant,
            challenge=challenge,
            submitted_flag="FLAG{old}",
            is_correct=False,
            points_awarded=0,
            attempt_number=1,
        )
        CTFSubmission.objects.filter(pk=old_sub.pk).update(
            submitted_at=timezone.now() - timedelta(seconds=15),
        )

        # This should succeed since 15s > 10s cooldown
        submission = submit_flag(participant.id, challenge.id, "FLAG{new}")
        assert submission.attempt_number == 2

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_no_rate_limit_when_cooldown_zero(self, mock_verify, active_event_no_cooldown, participant_user, db):
        """Cooldown of 0 means no time-based rate limiting."""
        challenge = CTFChallenge.objects.create(
            event=active_event_no_cooldown,
            name="No Limit Challenge",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$placeholder3",
        )
        part = CTFParticipant.objects.create(
            event=active_event_no_cooldown,
            user=participant_user,
            email=participant_user.email,
            name="No Limit Participant",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )

        # Both submissions should succeed (no cooldown)
        submit_flag(part.id, challenge.id, "FLAG{a}")
        submission = submit_flag(part.id, challenge.id, "FLAG{b}")
        assert submission.attempt_number == 2

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_rate_limit_is_per_challenge(self, mock_verify, participant, challenge, challenge_b):
        """Cooldown applies per challenge — submitting to challenge A doesn't block challenge B."""
        # Submit to challenge A
        submit_flag(participant.id, challenge.id, "FLAG{a}")

        # Submit to challenge B should succeed immediately
        submission = submit_flag(participant.id, challenge_b.id, "FLAG{b}")
        assert submission.attempt_number == 1

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_rate_limit_error_includes_retry_after(self, mock_verify, participant, challenge):
        """Rate limit error includes retry delay and retry timestamp details."""
        submit_flag(participant.id, challenge.id, "FLAG{first}")

        with pytest.raises(CTFRateLimitError) as exc_info:
            submit_flag(participant.id, challenge.id, "FLAG{second}")

        details = exc_info.value.details
        assert "retry_after_seconds" in details
        assert details["retry_after_seconds"] > 0
        assert details["retry_after_seconds"] <= 11  # cooldown is 10s, +1 ceiling
        assert "retry_at" in details
        assert datetime.fromisoformat(details["retry_at"])
        assert "retry at" in str(exc_info.value).lower()
        assert details["cooldown_seconds"] == 10


# ── Fixtures for attempt limit tests ─────────────────────────────────────


@pytest.fixture
def lockout_event(db, organizer_user):
    """Active event with lockout attempt limit mode."""
    return CTFEvent.objects.create(
        name="Lockout Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
        submission_cooldown_seconds=0,
        attempt_limit_mode="lockout",
    )


@pytest.fixture
def timeout_event(db, organizer_user):
    """Active event with timeout attempt limit mode (30s cooldown)."""
    return CTFEvent.objects.create(
        name="Timeout Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
        submission_cooldown_seconds=0,
        attempt_limit_mode="timeout",
        attempt_limit_cooldown_seconds=30,
    )


@pytest.fixture
def limited_challenge_lockout(db, lockout_event):
    """Challenge with 3 max attempts in lockout event."""
    return CTFChallenge.objects.create(
        event=lockout_event,
        name="Limited Lockout Challenge",
        description="Test",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$placeholder_lock",
        max_attempts=3,
    )


@pytest.fixture
def limited_challenge_timeout(db, timeout_event):
    """Challenge with 3 max attempts in timeout event."""
    return CTFChallenge.objects.create(
        event=timeout_event,
        name="Limited Timeout Challenge",
        description="Test",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$placeholder_time",
        max_attempts=3,
    )


@pytest.fixture
def lockout_participant(db, lockout_event, participant_user):
    return CTFParticipant.objects.create(
        event=lockout_event,
        user=participant_user,
        email=participant_user.email,
        name="Lockout Participant",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


@pytest.fixture
def timeout_participant(db, timeout_event, participant_user):
    return CTFParticipant.objects.create(
        event=timeout_event,
        user=participant_user,
        email=participant_user.email,
        name="Timeout Participant",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


@pytest.mark.django_db
class TestAttemptLimits:
    """Tests for challenge attempt limits (CTF-112)."""

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_lockout_blocks_after_max_attempts(self, mock_verify, lockout_participant, limited_challenge_lockout):
        """Lockout mode permanently blocks after max_attempts reached."""
        p = lockout_participant
        c = limited_challenge_lockout

        # Use all 3 attempts
        for i in range(3):
            submit_flag(p.id, c.id, f"FLAG{{wrong{i}}}")

        # 4th attempt should fail permanently
        with pytest.raises(CTFRateLimitError) as exc_info:
            submit_flag(p.id, c.id, "FLAG{wrong3}")

        assert exc_info.value.details["attempt_limit_mode"] == "lockout"
        assert exc_info.value.details["max_attempts"] == 3
        assert exc_info.value.details["attempts_used"] == 3

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_lockout_unlimited_when_zero(self, mock_verify, lockout_event, participant_user, db):
        """max_attempts=0 means unlimited attempts."""
        unlimited_challenge = CTFChallenge.objects.create(
            event=lockout_event,
            name="Unlimited Challenge",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$placeholder_unlim",
            max_attempts=0,
        )
        p = CTFParticipant.objects.create(
            event=lockout_event,
            user=participant_user,
            email=participant_user.email,
            name="Unlimited Participant",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )

        # Should allow many attempts without error
        for i in range(10):
            submit_flag(p.id, unlimited_challenge.id, f"FLAG{{wrong{i}}}")

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_timeout_blocks_within_cooldown(self, mock_verify, timeout_participant, limited_challenge_timeout):
        """Timeout mode blocks during cooldown period after max_attempts reached."""
        p = timeout_participant
        c = limited_challenge_timeout

        # Use all 3 attempts
        for i in range(3):
            submit_flag(p.id, c.id, f"FLAG{{wrong{i}}}")

        # 4th attempt within cooldown should fail with retry_after
        with pytest.raises(CTFRateLimitError) as exc_info:
            submit_flag(p.id, c.id, "FLAG{wrong3}")

        assert exc_info.value.details["attempt_limit_mode"] == "timeout"
        assert "retry_after_seconds" in exc_info.value.details

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_timeout_allows_after_cooldown_elapsed(self, mock_verify, timeout_participant, limited_challenge_timeout):
        """Timeout mode allows retry after cooldown period elapses."""
        p = timeout_participant
        c = limited_challenge_timeout

        # Create 3 submissions backdated past the cooldown window (30s)
        for i in range(3):
            sub = CTFSubmission.objects.create(
                participant=p,
                challenge=c,
                submitted_flag=f"FLAG{{old{i}}}",
                is_correct=False,
                points_awarded=0,
                attempt_number=i + 1,
            )
            CTFSubmission.objects.filter(pk=sub.pk).update(
                submitted_at=timezone.now() - timedelta(seconds=60),
            )

        # Cooldown elapsed — should succeed
        submission = submit_flag(p.id, c.id, "FLAG{retry}")
        assert submission is not None
        assert submission.attempt_number == 1  # reset after cooldown

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_timeout_resets_attempt_count_after_cooldown(
        self, mock_verify, timeout_participant, limited_challenge_timeout
    ):
        """After timeout cooldown, attempt count resets and allows max_attempts again."""
        p = timeout_participant
        c = limited_challenge_timeout

        # Create 3 old submissions past cooldown
        for i in range(3):
            sub = CTFSubmission.objects.create(
                participant=p,
                challenge=c,
                submitted_flag=f"FLAG{{old{i}}}",
                is_correct=False,
                points_awarded=0,
                attempt_number=i + 1,
            )
            CTFSubmission.objects.filter(pk=sub.pk).update(
                submitted_at=timezone.now() - timedelta(seconds=60),
            )

        # Should get 3 more attempts after reset
        for i in range(3):
            submit_flag(p.id, c.id, f"FLAG{{new{i}}}")

        # 4th should fail again
        with pytest.raises(CTFRateLimitError):
            submit_flag(p.id, c.id, "FLAG{too_many}")

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_lockout_is_default_mode(self, mock_verify, db, organizer_user, participant_user):
        """Default attempt_limit_mode is lockout."""
        event = CTFEvent.objects.create(
            name="Default Mode Event",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
        )
        assert event.attempt_limit_mode == "lockout"


# ── Fixtures for time-boundary tests ─────────────────────────────────────


@pytest.fixture
def future_start_event(db, organizer_user):
    """Active event whose start time is in the future."""
    return CTFEvent.objects.create(
        name="Future Start Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() + timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=8),
        scenario_id="basic",
        submission_cooldown_seconds=0,
    )


@pytest.fixture
def past_end_event(db, organizer_user):
    """Active event whose end time is in the past."""
    return CTFEvent.objects.create(
        name="Past End Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=8),
        event_end=timezone.now() - timedelta(hours=1),
        scenario_id="basic",
        submission_cooldown_seconds=0,
    )


@pytest.mark.django_db
class TestTimeBoundaryEnforcement:
    """Tests for event time-boundary enforcement (CTF-702).

    Submissions must be rejected when outside the event_start/event_end
    window, even if the event status is ACTIVE.
    """

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_rejects_before_event_start(self, mock_verify, future_start_event, participant_user, db):
        """Flag submission is rejected when now < event_start, even if ACTIVE."""
        challenge = CTFChallenge.objects.create(
            event=future_start_event,
            name="Early Challenge",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$placeholder_early",
        )
        participant = CTFParticipant.objects.create(
            event=future_start_event,
            user=participant_user,
            email=participant_user.email,
            name="Early Participant",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )

        with pytest.raises(CTFStateError, match="not within its competition window"):
            submit_flag(participant.id, challenge.id, "FLAG{too_early}")

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_rejects_after_event_end(self, mock_verify, past_end_event, participant_user, db):
        """Flag submission is rejected when now > event_end, even if ACTIVE."""
        challenge = CTFChallenge.objects.create(
            event=past_end_event,
            name="Late Challenge",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$placeholder_late",
        )
        participant = CTFParticipant.objects.create(
            event=past_end_event,
            user=participant_user,
            email=participant_user.email,
            name="Late Participant",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )

        with pytest.raises(CTFStateError, match="not within its competition window"):
            submit_flag(participant.id, challenge.id, "FLAG{too_late}")

    @patch("ctf.services.submission.verify_flag", return_value=False)
    def test_allows_within_window(self, mock_verify, participant, challenge):
        """Flag submission succeeds when within the event time window."""
        submission = submit_flag(participant.id, challenge.id, "FLAG{on_time}")
        assert submission is not None
