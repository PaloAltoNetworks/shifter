"""Tests for CTF Submission service — rate limiting.

Integration-style tests using real DB objects. Only verify_flag is mocked
since it requires bcrypt hashes.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from ctf.enums import (
    ChallengeCategory,
    ChallengeDifficulty,
    EventStatus,
    ParticipantStatus,
)
from ctf.exceptions import CTFRateLimitError
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
        """Rate limit error details include retry_after_seconds for the client."""
        submit_flag(participant.id, challenge.id, "FLAG{first}")

        with pytest.raises(CTFRateLimitError) as exc_info:
            submit_flag(participant.id, challenge.id, "FLAG{second}")

        details = exc_info.value.details
        assert "retry_after_seconds" in details
        assert details["retry_after_seconds"] > 0
        assert details["retry_after_seconds"] <= 11  # cooldown is 10s, +1 ceiling
        assert details["cooldown_seconds"] == 10
