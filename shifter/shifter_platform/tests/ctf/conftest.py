"""Pytest fixtures for CTF tests.

This module provides shared fixtures for all CTF test modules.
Uses pytest fixtures to avoid OOM issues from inline mocks.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
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
from shared.auth import CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.test import Client

User = get_user_model()


# -----------------------------------------------------------------------------
# In-memory model builders (no DB required)
# -----------------------------------------------------------------------------


def make_ctf_event(**overrides) -> CTFEvent:
    """Build an in-memory CTFEvent without saving.

    Uses `created_by_id` to avoid Django FK descriptor validation.
    All defaults can be overridden via kwargs.
    """
    now = timezone.now()
    defaults = {
        "id": uuid4(),
        "name": "Test CTF Event",
        "created_by_id": 1,
        "status": EventStatus.REGISTRATION.value,
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


def make_challenge(event=None, **overrides) -> CTFChallenge:
    """Build an in-memory CTFChallenge without saving."""
    if event is None:
        event = make_ctf_event()
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
        "release_time": None,
        "order": 0,
    }
    defaults.update(overrides)
    return CTFChallenge(**defaults)


def make_team(event=None, **overrides) -> CTFTeam:
    """Build an in-memory CTFTeam without saving."""
    if event is None:
        event = make_ctf_event(team_mode=True, team_size_limit=4)
    defaults = {
        "id": uuid4(),
        "event": event,
        "name": "Test Team",
        "invite_code": "test-invite-code-12345678",
    }
    defaults.update(overrides)
    return CTFTeam(**defaults)


def make_participant(event=None, **overrides) -> CTFParticipant:
    """Build an in-memory CTFParticipant without saving.

    Uses `user_id` to avoid Django FK descriptor validation.
    """
    if event is None:
        event = make_ctf_event()
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


def make_scheduled_task(event=None, **overrides) -> CTFScheduledTask:
    """Build an in-memory CTFScheduledTask without saving."""
    if event is None:
        event = make_ctf_event()
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


# -----------------------------------------------------------------------------
# User Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def organizer_user(db) -> User:
    """Create a CTF organizer user with profile and group."""
    from management.services import get_user_profile

    user = User.objects.create_user(
        username="organizer@test.com",
        email="organizer@test.com",
        password="testpass123",  # nosec B106
        first_name="Test",
        last_name="Organizer",
    )
    group, _ = Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)
    user.groups.add(group)
    profile = get_user_profile(user)
    profile.user_type = "ctf_organizer"
    profile.save(update_fields=["user_type"])
    return user


@pytest.fixture
def participant_user(db) -> User:
    """Create a CTF participant user with profile and group."""
    from management.services import get_user_profile

    user = User.objects.create_user(
        username="participant@test.com",
        email="participant@test.com",
        password="testpass123",  # nosec B106
        first_name="Test",
        last_name="Participant",
    )
    group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
    user.groups.add(group)
    profile = get_user_profile(user)
    profile.user_type = "ctf_participant"
    profile.save(update_fields=["user_type"])
    return user


@pytest.fixture
def second_participant_user(db) -> User:
    """Create a second CTF participant user with profile and group."""
    from management.services import get_user_profile

    user = User.objects.create_user(
        username="participant2@test.com",
        email="participant2@test.com",
        password="testpass123",  # nosec B106
        first_name="Second",
        last_name="Participant",
    )
    group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
    user.groups.add(group)
    profile = get_user_profile(user)
    profile.user_type = "ctf_participant"
    profile.save(update_fields=["user_type"])
    return user


@pytest.fixture
def standard_user(db) -> User:
    """Create a standard (non-CTF) user."""
    user = User.objects.create_user(
        username="standard@test.com",
        email="standard@test.com",
        password="testpass123",  # nosec B106
        first_name="Standard",
        last_name="User",
    )
    # Standard users get default profile via get_user_profile if accessed
    return user


@pytest.fixture
def admin_user(db) -> User:
    """Create a superuser."""
    user = User.objects.create_superuser(
        username="admin@test.com",
        email="admin@test.com",
        password="adminpass123",  # nosec B106
    )
    return user


# -----------------------------------------------------------------------------
# Event Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def ctf_event(db, organizer_user) -> CTFEvent:
    """Create a scheduled CTF event."""
    return CTFEvent.objects.create(
        name="Test CTF Event",
        description="A test CTF event for unit testing",
        created_by=organizer_user,
        status=EventStatus.REGISTRATION.value,
        event_start=timezone.now() + timedelta(days=1),
        event_end=timezone.now() + timedelta(days=1, hours=8),
        scenario_id="basic",
        auto_cleanup=True,
        cleanup_delay_hours=24,
        team_mode=False,
    )


@pytest.fixture
def ctf_event_draft(db, organizer_user) -> CTFEvent:
    """Create a draft CTF event."""
    return CTFEvent.objects.create(
        name="Draft CTF Event",
        description="A draft event",
        created_by=organizer_user,
        status=EventStatus.DRAFT.value,
        event_start=timezone.now() + timedelta(days=7),
        event_end=timezone.now() + timedelta(days=7, hours=8),
        scenario_id="basic",
    )


@pytest.fixture
def ctf_event_active(db, organizer_user) -> CTFEvent:
    """Create an active CTF event."""
    return CTFEvent.objects.create(
        name="Active CTF Event",
        description="An active event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
    )


@pytest.fixture
def ctf_event_team(db, organizer_user) -> CTFEvent:
    """Create a team-based CTF event."""
    return CTFEvent.objects.create(
        name="Team CTF Event",
        description="A team-based event",
        created_by=organizer_user,
        status=EventStatus.REGISTRATION.value,
        event_start=timezone.now() + timedelta(days=1),
        event_end=timezone.now() + timedelta(days=1, hours=8),
        scenario_id="basic",
        team_mode=True,
        team_size_limit=4,
    )


# -----------------------------------------------------------------------------
# Challenge Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def ctf_challenge(db, ctf_event) -> CTFChallenge:
    """Create a basic challenge."""
    return CTFChallenge.objects.create(
        event=ctf_event,
        name="Test Challenge",
        description="Find the flag in the source code",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$test_hash_placeholder",
        flag_format="FLAG{...}",
    )


@pytest.fixture
def ctf_challenge_with_hint(db, ctf_event) -> CTFChallenge:
    """Create a challenge with hint."""
    return CTFChallenge.objects.create(
        event=ctf_event,
        name="Challenge With Hint",
        description="A challenge with a hint",
        category=ChallengeCategory.CRYPTO.value,
        points=200,
        difficulty=ChallengeDifficulty.MEDIUM.value,
        flag_hash="$2b$12$another_hash_placeholder",
        hint="Look at the cipher mode",
        hint_penalty=25,
    )


@pytest.fixture
def ctf_challenge_delayed(db, ctf_event) -> CTFChallenge:
    """Create a challenge with delayed release."""
    return CTFChallenge.objects.create(
        event=ctf_event,
        name="Delayed Challenge",
        description="Released later in the event",
        category=ChallengeCategory.PWN.value,
        points=300,
        difficulty=ChallengeDifficulty.HARD.value,
        flag_hash="$2b$12$delayed_hash_placeholder",
        release_time=ctf_event.event_start + timedelta(hours=2),
    )


# -----------------------------------------------------------------------------
# Team Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def ctf_team(db, ctf_event_team) -> CTFTeam:
    """Create a team."""
    return CTFTeam.objects.create(
        event=ctf_event_team,
        name="Test Team",
    )


# -----------------------------------------------------------------------------
# Participant Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def ctf_participant(db, ctf_event, participant_user) -> CTFParticipant:
    """Create an active participant."""
    return CTFParticipant.objects.create(
        event=ctf_event,
        user=participant_user,
        email=participant_user.email,
        name="Test Participant",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


@pytest.fixture
def ctf_participant_invited(db, ctf_event) -> CTFParticipant:
    """Create an invited (not yet registered) participant."""
    return CTFParticipant.objects.create(
        event=ctf_event,
        email="invited@test.com",
        name="Invited Participant",
        status=ParticipantStatus.INVITED.value,
        invited_at=timezone.now(),
    )


@pytest.fixture
def ctf_participant_team(db, ctf_event_team, ctf_team, participant_user) -> CTFParticipant:
    """Create a participant in a team."""
    return CTFParticipant.objects.create(
        event=ctf_event_team,
        user=participant_user,
        email=participant_user.email,
        name="Team Participant",
        team=ctf_team,
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


# -----------------------------------------------------------------------------
# Submission Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def ctf_submission_correct(db, ctf_participant, ctf_challenge) -> CTFSubmission:
    """Create a correct submission."""
    return CTFSubmission.objects.create(
        participant=ctf_participant,
        challenge=ctf_challenge,
        submitted_flag="FLAG{correct}",
        is_correct=True,
        points_awarded=ctf_challenge.points,
        attempt_number=1,
        ip_address="192.168.1.1",
    )


@pytest.fixture
def ctf_submission_incorrect(db, ctf_participant, ctf_challenge) -> CTFSubmission:
    """Create an incorrect submission."""
    return CTFSubmission.objects.create(
        participant=ctf_participant,
        challenge=ctf_challenge,
        submitted_flag="FLAG{wrong}",
        is_correct=False,
        points_awarded=0,
        attempt_number=1,
        ip_address="192.168.1.1",
    )


# -----------------------------------------------------------------------------
# Authenticated Client Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def authenticated_organizer_client(client: Client, organizer_user) -> Client:
    """Client logged in as organizer."""
    client.force_login(organizer_user)
    return client


@pytest.fixture
def authenticated_participant_client(client: Client, participant_user) -> Client:
    """Client logged in as participant."""
    client.force_login(participant_user)
    return client


@pytest.fixture
def authenticated_admin_client(client: Client, admin_user) -> Client:
    """Client logged in as admin."""
    client.force_login(admin_user)
    return client


@pytest.fixture
def authenticated_standard_client(client: Client, standard_user) -> Client:
    """Client logged in as standard user."""
    client.force_login(standard_user)
    return client


@pytest.fixture
def second_organizer_user(db) -> User:
    """Create a second CTF organizer user with profile and group."""
    from management.services import get_user_profile

    user = User.objects.create_user(
        username="organizer2@test.com",
        email="organizer2@test.com",
        password="testpass123",  # nosec B106
        first_name="Second",
        last_name="Organizer",
    )
    group, _ = Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)
    user.groups.add(group)
    profile = get_user_profile(user)
    profile.user_type = "ctf_organizer"
    profile.save(update_fields=["user_type"])
    return user


@pytest.fixture
def request_factory():
    """Provide Django RequestFactory."""
    from django.test import RequestFactory

    return RequestFactory()


# -----------------------------------------------------------------------------
# Mock Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_range_service(mocker) -> MagicMock:
    """Mock the CMS range creation service."""
    mock = mocker.patch(
        "cms.services.create_range",
        return_value=MagicMock(id=1, status="provisioning"),
    )
    return mock


@pytest.fixture
def mock_email_backend(mocker) -> MagicMock:
    """Mock email sending."""
    mock = mocker.patch("django.core.mail.send_mail", return_value=1)
    return mock
