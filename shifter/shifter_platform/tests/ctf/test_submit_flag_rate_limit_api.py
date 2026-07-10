"""API integration tests for CTF-114 submission cooldown (rate limiting)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.utils import timezone

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus, ParticipantStatus
from ctf.models import CTFChallenge, CTFEvent, CTFParticipant
from tests.ctf._api_flow_helpers import call_json as _json

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_submit_flag_rate_limited_returns_retry_envelope(
    authenticated_participant_client: Client,
    participant_user,
    organizer_user,
    db,
):
    """CTF-114: cooldown violation returns 429 with Retry-After and retry fields in JSON."""
    event = CTFEvent.objects.create(
        name="Rate Limit API Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
        submission_cooldown_seconds=10,
    )
    challenge = CTFChallenge.objects.create(
        event=event,
        name="Cooldown Challenge",
        description="Test",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$placeholder",
    )
    CTFParticipant.objects.create(
        event=event,
        user=participant_user,
        email=participant_user.email,
        name="Rate Limit API Participant",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )
    first = _json(
        authenticated_participant_client,
        "post",
        "api_submit_flag",
        kwargs={"challenge_id": challenge.id},
        body={"flag": "FLAG{first}"},
    )
    assert first.status_code == 200

    second = _json(
        authenticated_participant_client,
        "post",
        "api_submit_flag",
        kwargs={"challenge_id": challenge.id},
        body={"flag": "FLAG{second}"},
    )
    assert second.status_code == 429
    assert second.headers.get("Retry-After")
    body = second.json()
    assert body.get("retry_after_seconds")
    assert int(body["retry_after_seconds"]) > 0
    assert body.get("error")
