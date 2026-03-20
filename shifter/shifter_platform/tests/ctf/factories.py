"""Factory functions for creating CTF test data.

Provides helper functions to create test data dictionaries with sensible defaults.
Override specific fields by passing keyword arguments.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from ctf.enums import (
    ChallengeCategory,
    ChallengeDifficulty,
    EventStatus,
    NotificationStatus,
    NotificationType,
    ParticipantStatus,
    ScheduledTaskStatus,
    ScheduledTaskType,
)


def create_event_data(**overrides: Any) -> dict[str, Any]:
    """Create event data dictionary for testing.

    Args:
        **overrides: Fields to override from defaults.

    Returns:
        Dictionary with event data.
    """
    now = timezone.now()
    data = {
        "name": "Test CTF Event",
        "description": "A test CTF event for testing purposes",
        "status": EventStatus.DRAFT.value,
        "event_start": now + timedelta(days=7),
        "event_end": now + timedelta(days=7, hours=8),
        "scenario_id": "basic",
        "auto_cleanup": True,
        "cleanup_delay_hours": 24,
        "team_mode": False,
        "range_spinup_minutes": 30,
    }
    data.update(overrides)
    return data


def create_challenge_data(**overrides: Any) -> dict[str, Any]:
    """Create challenge data dictionary for testing.

    Args:
        **overrides: Fields to override from defaults.

    Returns:
        Dictionary with challenge data.
    """
    data = {
        "name": "Test Challenge",
        "description": "Find the hidden flag in this challenge",
        "category": ChallengeCategory.WEB.value,
        "points": 100,
        "difficulty": ChallengeDifficulty.MEDIUM.value,
        "flag": "FLAG{test_flag_123}",  # Unhashed, for service layer
        "flag_format": "FLAG{...}",
        "order": 0,
    }
    data.update(overrides)
    return data


def create_challenge_model_data(**overrides: Any) -> dict[str, Any]:
    """Create challenge data dictionary for direct model creation.

    Args:
        **overrides: Fields to override from defaults.

    Returns:
        Dictionary with challenge data (includes flag_hash).
    """
    data = {
        "name": "Test Challenge",
        "description": "Find the hidden flag in this challenge",
        "category": ChallengeCategory.WEB.value,
        "points": 100,
        "difficulty": ChallengeDifficulty.MEDIUM.value,
        "flag_hash": "$2b$12$placeholder_hash",  # Pre-hashed for model
        "flag_format": "FLAG{...}",
        "order": 0,
    }
    data.update(overrides)
    return data


def create_participant_data(**overrides: Any) -> dict[str, Any]:
    """Create participant data dictionary for testing.

    Args:
        **overrides: Fields to override from defaults.

    Returns:
        Dictionary with participant data.
    """
    data = {
        "email": "participant@test.com",
        "name": "Test Participant",
        "status": ParticipantStatus.INVITED.value,
    }
    data.update(overrides)
    return data


def create_team_data(**overrides: Any) -> dict[str, Any]:
    """Create team data dictionary for testing.

    Args:
        **overrides: Fields to override from defaults.

    Returns:
        Dictionary with team data.
    """
    data = {
        "name": "Test Team",
    }
    data.update(overrides)
    return data


def create_submission_data(**overrides: Any) -> dict[str, Any]:
    """Create submission data dictionary for testing.

    Args:
        **overrides: Fields to override from defaults.

    Returns:
        Dictionary with submission data.
    """
    data = {
        "submitted_flag": "FLAG{test}",
        "is_correct": False,
        "points_awarded": 0,
        "hint_used": False,
        "attempt_number": 1,
        "ip_address": "192.168.1.1",
    }
    data.update(overrides)
    return data


def create_notification_data(**overrides: Any) -> dict[str, Any]:
    """Create notification data dictionary for testing.

    Args:
        **overrides: Fields to override from defaults.

    Returns:
        Dictionary with notification data.
    """
    data = {
        "notification_type": NotificationType.ANNOUNCEMENT.value,
        "subject": "Test Notification",
        "body": "This is a test notification body.",
        "status": NotificationStatus.DRAFT.value,
        "recipient_filter": "participants",
    }
    data.update(overrides)
    return data


def create_scheduled_task_data(**overrides: Any) -> dict[str, Any]:
    """Create scheduled task data dictionary for testing.

    Args:
        **overrides: Fields to override from defaults.

    Returns:
        Dictionary with scheduled task data.
    """
    data = {
        "task_type": ScheduledTaskType.SPIN_UP_RANGES.value,
        "scheduled_for": timezone.now() + timedelta(hours=1),
        "status": ScheduledTaskStatus.PENDING.value,
        "metadata": {},
    }
    data.update(overrides)
    return data


def create_bulk_participants_csv(count: int = 5) -> str:
    """Create CSV content for bulk participant import.

    Args:
        count: Number of participants to include.

    Returns:
        CSV string with participant data.
    """
    lines = []
    for i in range(1, count + 1):
        lines.append(f"Participant {i},participant{i}@test.com")
    return "\n".join(lines)
