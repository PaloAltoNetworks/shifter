"""Tests for CTF-111: Challenge Release Scheduling.

Tests the automatic transition of challenges from HIDDEN to VISIBLE
at their scheduled release_time via the scheduler infrastructure.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from ctf.enums import (
    ChallengeCategory,
    ChallengeDifficulty,
    ChallengeVisibility,
    EventStatus,
    ScheduledTaskStatus,
    ScheduledTaskType,
)
from ctf.models import CTFChallenge, CTFEvent, CTFScheduledTask
from ctf.services.challenge import (
    _sync_release_task,
    create_challenge,
    release_challenge,
    update_challenge,
)

# Shared defaults for creating challenges via objects.create
_CHALLENGE_DEFAULTS = {
    "description": "Test challenge description",
    "category": ChallengeCategory.WEB.value,
    "points": 100,
    "difficulty": ChallengeDifficulty.EASY.value,
    "flag_hash": "$2b$12$test_hash_placeholder",
}


@pytest.fixture
def active_event(db, organizer_user) -> CTFEvent:
    """An ACTIVE event whose time window spans now (release_time tests need this)."""
    return CTFEvent.objects.create(
        name="Active Release Event",
        description="Event for release scheduling tests",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=8),
        scenario_id="basic",
    )


# ---------------------------------------------------------------------------
# release_challenge() service function
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReleaseChallenge:
    """Tests for the release_challenge service function."""

    def test_transitions_hidden_to_visible(self, active_event):
        """A HIDDEN challenge is transitioned to VISIBLE."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Hidden Challenge",
            **_CHALLENGE_DEFAULTS,
            visibility=ChallengeVisibility.HIDDEN.value,
            release_time=active_event.event_start + timedelta(minutes=30),
        )

        result = release_challenge(challenge.pk)

        assert result.visibility == ChallengeVisibility.VISIBLE.value
        challenge.refresh_from_db()
        assert challenge.visibility == ChallengeVisibility.VISIBLE.value

    def test_skips_already_visible(self, active_event):
        """A VISIBLE challenge is left unchanged."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Visible Challenge",
            **_CHALLENGE_DEFAULTS,
            visibility=ChallengeVisibility.VISIBLE.value,
        )

        result = release_challenge(challenge.pk)

        assert result.visibility == ChallengeVisibility.VISIBLE.value

    def test_skips_locked(self, active_event):
        """A LOCKED challenge is left unchanged."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Locked Challenge",
            **_CHALLENGE_DEFAULTS,
            visibility=ChallengeVisibility.LOCKED.value,
        )

        result = release_challenge(challenge.pk)

        assert result.visibility == ChallengeVisibility.LOCKED.value

    def test_not_found_raises(self):
        """Non-existent challenge raises CTFNotFoundError."""
        from ctf.exceptions import CTFNotFoundError

        with pytest.raises(CTFNotFoundError):
            release_challenge(uuid4())


# ---------------------------------------------------------------------------
# _sync_release_task() - task creation and cancellation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncReleaseTask:
    """Tests for _sync_release_task helper."""

    def test_creates_task_for_hidden_challenge_with_future_release(self, active_event):
        """A HIDDEN challenge with future release_time gets a scheduled task."""
        release_time = timezone.now() + timedelta(hours=2)
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Scheduled Challenge",
            **_CHALLENGE_DEFAULTS,
            visibility=ChallengeVisibility.HIDDEN.value,
            release_time=release_time,
        )

        _sync_release_task(challenge)

        task = CTFScheduledTask.objects.get(
            event=active_event,
            task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
            metadata__challenge_id=str(challenge.pk),
        )
        assert task.status == ScheduledTaskStatus.PENDING.value
        assert task.scheduled_for == release_time

    def test_no_task_for_visible_challenge(self, active_event):
        """A VISIBLE challenge does not get a release task."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Visible Challenge",
            **_CHALLENGE_DEFAULTS,
            visibility=ChallengeVisibility.VISIBLE.value,
            release_time=timezone.now() + timedelta(hours=2),
        )

        _sync_release_task(challenge)

        assert not CTFScheduledTask.objects.filter(
            task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
            metadata__challenge_id=str(challenge.pk),
        ).exists()

    def test_no_task_for_past_release_time(self, active_event):
        """A HIDDEN challenge with past release_time does not get a task."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Past Release",
            **_CHALLENGE_DEFAULTS,
            visibility=ChallengeVisibility.HIDDEN.value,
            release_time=active_event.event_start + timedelta(minutes=5),
        )

        _sync_release_task(challenge)

        assert not CTFScheduledTask.objects.filter(
            task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
            metadata__challenge_id=str(challenge.pk),
            status=ScheduledTaskStatus.PENDING.value,
        ).exists()

    def test_cancels_old_task_on_reschedule(self, active_event):
        """Rescheduling cancels the old task and creates a new one."""
        release_time = timezone.now() + timedelta(hours=2)
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Reschedule Me",
            **_CHALLENGE_DEFAULTS,
            visibility=ChallengeVisibility.HIDDEN.value,
            release_time=release_time,
        )
        _sync_release_task(challenge)

        # Reschedule to a later time
        new_release_time = timezone.now() + timedelta(hours=4)
        challenge.release_time = new_release_time
        challenge.save(update_fields=["release_time"])
        _sync_release_task(challenge)

        tasks = CTFScheduledTask.objects.filter(
            task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
            metadata__challenge_id=str(challenge.pk),
        )
        assert tasks.filter(status=ScheduledTaskStatus.CANCELLED.value).count() == 1
        pending = tasks.filter(status=ScheduledTaskStatus.PENDING.value)
        assert pending.count() == 1
        assert pending.first().scheduled_for == new_release_time

    def test_cancels_task_when_release_time_cleared(self, active_event):
        """Clearing release_time cancels any pending release task."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Clear Release",
            **_CHALLENGE_DEFAULTS,
            visibility=ChallengeVisibility.HIDDEN.value,
            release_time=timezone.now() + timedelta(hours=2),
        )
        _sync_release_task(challenge)
        assert (
            CTFScheduledTask.objects.filter(
                task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
                metadata__challenge_id=str(challenge.pk),
                status=ScheduledTaskStatus.PENDING.value,
            ).count()
            == 1
        )

        # Clear release_time
        challenge.release_time = None
        challenge.save(update_fields=["release_time"])
        _sync_release_task(challenge)

        assert not CTFScheduledTask.objects.filter(
            task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
            metadata__challenge_id=str(challenge.pk),
            status=ScheduledTaskStatus.PENDING.value,
        ).exists()


# ---------------------------------------------------------------------------
# Integration with create_challenge / update_challenge
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChallengeServiceIntegration:
    """Tests that create/update_challenge sync release tasks."""

    def test_create_challenge_with_release_time_schedules_task(self, ctf_event):
        """Creating a HIDDEN challenge with release_time schedules a task."""
        release_time = ctf_event.event_start + timedelta(hours=2)
        challenge = create_challenge(
            ctf_event.pk,
            {
                "name": "Scheduled via Create",
                "description": "Test challenge",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{test}",
                "visibility": ChallengeVisibility.HIDDEN.value,
                "release_time": release_time,
            },
        )

        assert CTFScheduledTask.objects.filter(
            event=ctf_event,
            task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
            metadata__challenge_id=str(challenge.pk),
            status=ScheduledTaskStatus.PENDING.value,
        ).exists()

    def test_create_challenge_visible_no_task(self, ctf_event):
        """Creating a VISIBLE challenge with release_time does NOT schedule a task."""
        release_time = ctf_event.event_start + timedelta(hours=2)
        challenge = create_challenge(
            ctf_event.pk,
            {
                "name": "Visible with Release",
                "description": "Test challenge",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{test}",
                "visibility": ChallengeVisibility.VISIBLE.value,
                "release_time": release_time,
            },
        )

        assert not CTFScheduledTask.objects.filter(
            task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
            metadata__challenge_id=str(challenge.pk),
        ).exists()

    def test_update_challenge_reschedules_task(self, ctf_event):
        """Updating release_time on a HIDDEN challenge reschedules the task."""
        release_time = ctf_event.event_start + timedelta(hours=2)
        challenge = create_challenge(
            ctf_event.pk,
            {
                "name": "Update Me",
                "description": "Test challenge",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{test}",
                "visibility": ChallengeVisibility.HIDDEN.value,
                "release_time": release_time,
            },
        )

        new_release_time = ctf_event.event_start + timedelta(hours=4)
        update_challenge(challenge.pk, {"release_time": new_release_time})

        pending = CTFScheduledTask.objects.filter(
            task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
            metadata__challenge_id=str(challenge.pk),
            status=ScheduledTaskStatus.PENDING.value,
        )
        assert pending.count() == 1
        assert pending.first().scheduled_for == new_release_time


# ---------------------------------------------------------------------------
# Scheduler handler
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSchedulerHandler:
    """Tests for the RELEASE_CHALLENGE scheduler handler."""

    def test_handler_calls_release_challenge(self, active_event):
        """The scheduler handler calls the release_challenge service."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Scheduler Test",
            **_CHALLENGE_DEFAULTS,
            visibility=ChallengeVisibility.HIDDEN.value,
            release_time=active_event.event_start + timedelta(minutes=30),
        )
        task = CTFScheduledTask.objects.create(
            event=active_event,
            task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
            scheduled_for=active_event.event_start + timedelta(minutes=30),
            metadata={"challenge_id": str(challenge.pk)},
        )

        from ctf.management.commands.run_ctf_scheduler import _handle_release_challenge

        _handle_release_challenge(task)

        challenge.refresh_from_db()
        assert challenge.visibility == ChallengeVisibility.VISIBLE.value

    def test_handler_raises_on_missing_metadata(self, active_event):
        """Handler raises ValueError if challenge_id not in metadata."""
        task = CTFScheduledTask.objects.create(
            event=active_event,
            task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
            scheduled_for=timezone.now(),
            metadata={},
        )

        from ctf.management.commands.run_ctf_scheduler import _handle_release_challenge

        with pytest.raises(ValueError, match="missing challenge_id"):
            _handle_release_challenge(task)

    def test_handler_registered_in_task_handlers(self):
        """RELEASE_CHALLENGE is registered in the TASK_HANDLERS dict."""
        from ctf.management.commands.run_ctf_scheduler import TASK_HANDLERS

        assert ScheduledTaskType.RELEASE_CHALLENGE.value in TASK_HANDLERS
