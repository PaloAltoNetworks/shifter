"""Behavior tests for explicit CTF event scoring mode (issue #520 / CTF-002, CTF-201).

Covers the mode config field default and backward compatibility, the scoring-mode
strategy dispatch, the submission service routing through it, organizer visibility
(API payload + form), and invalid-mode rejection at the event-config boundary.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ctf.enums import (
    ChallengeCategory,
    ChallengeDifficulty,
    EventStatus,
    ParticipantStatus,
    ScoringMode,
)
from ctf.exceptions import CTFValidationError
from ctf.forms import CTFEventForm
from ctf.models import CTFChallenge, CTFEvent, CTFParticipant
from ctf.services.challenge import hash_flag
from ctf.services.event import create_event, update_event
from ctf.services.scoring import calculate_solve_points, get_scoring_strategy
from ctf.services.scoring._strategy import StandardScoringStrategy
from ctf.services.submission import submit_flag
from ctf.views.api.events import _event_detail_payload

# ---------------------------------------------------------------------------
# Model default / backward compatibility
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_new_event_defaults_to_standard(organizer_user):
    """An event created without a scoring mode defaults to standard (CTF-201)."""
    now = timezone.now()
    event = CTFEvent.objects.create(
        name="Default Mode Event",
        created_by=organizer_user,
        status=EventStatus.DRAFT.value,
        event_start=now + timedelta(days=1),
        event_end=now + timedelta(days=1, hours=8),
    )
    event.refresh_from_db()
    assert event.scoring_mode == ScoringMode.STANDARD.value == "standard"


def test_scoring_mode_choices_include_standard():
    """The mode enum exposes standard via the shared choices() contract."""
    assert ("standard", "Standard") in ScoringMode.choices()


# ---------------------------------------------------------------------------
# Strategy dispatch
# ---------------------------------------------------------------------------


def _in_memory_challenge(points: int = 100) -> CTFChallenge:
    return CTFChallenge(name="C", points=points, category=ChallengeCategory.WEB.value)


def test_get_scoring_strategy_standard():
    assert isinstance(get_scoring_strategy("standard"), StandardScoringStrategy)


def test_get_scoring_strategy_unknown_falls_back_to_standard():
    """An unknown/drifted mode value falls back to standard rather than raising."""
    assert isinstance(get_scoring_strategy("does-not-exist"), StandardScoringStrategy)


def test_calculate_solve_points_standard_full_value():
    """Standard mode awards the challenge's fixed point value with no hint penalty."""
    event = CTFEvent(scoring_mode=ScoringMode.STANDARD.value)
    challenge = _in_memory_challenge(points=100)
    assert calculate_solve_points(event, challenge, 0) == 100


def test_calculate_solve_points_standard_applies_hint_penalty():
    """Standard mode still applies the cumulative hint penalty as an explicit modifier."""
    event = CTFEvent(scoring_mode=ScoringMode.STANDARD.value)
    challenge = _in_memory_challenge(points=100)
    # 20% penalty on a 100-point challenge -> 80.
    assert calculate_solve_points(event, challenge, 20) == 80
    assert calculate_solve_points(event, challenge, 20) == challenge.calculate_points_with_penalty(20)


# ---------------------------------------------------------------------------
# Submission service routes through the strategy
# ---------------------------------------------------------------------------


@pytest.fixture
def active_event(db, organizer_user):
    now = timezone.now()
    return CTFEvent.objects.create(
        name="Scoring Mode Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=now - timedelta(hours=1),
        event_end=now + timedelta(hours=7),
    )


@pytest.fixture
def solvable_challenge(db, active_event):
    # Real bcrypt flag hash so verify_flag accepts "FLAG{ok}" without mocking a
    # first-party seam (ADR-019 boundary-mock policy).
    return CTFChallenge.objects.create(
        event=active_event,
        name="Solvable",
        description="Solve me",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash=hash_flag("FLAG{ok}"),
        flag_format="FLAG{...}",
    )


@pytest.fixture
def active_participant(db, active_event, participant_user):
    return CTFParticipant.objects.create(
        event=active_event,
        user=participant_user,
        email=participant_user.email,
        name="Solver",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


@pytest.mark.django_db
def test_correct_solve_awards_standard_points(active_participant, solvable_challenge):
    """A correct solve on a standard-mode event awards the full challenge value.

    Exercises the real submit_flag path, which now computes the solve value via
    the scoring-mode dispatch (calculate_solve_points); the awarded points equal
    the challenge's fixed value, confirming standard behavior is unchanged.
    """
    submission = submit_flag(active_participant.id, solvable_challenge.id, "FLAG{ok}")
    assert submission.is_correct
    assert submission.points_awarded == solvable_challenge.points == 100


# ---------------------------------------------------------------------------
# Organizer config boundary: acceptance, defaulting, invalid rejection
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_event_accepts_scoring_mode(organizer_user):
    now = timezone.now()
    event = create_event(
        organizer_user,
        {
            "name": "Configured",
            "event_start": now + timedelta(days=1),
            "event_end": now + timedelta(days=1, hours=8),
            "scoring_mode": "standard",
        },
    )
    assert event.scoring_mode == "standard"


@pytest.mark.django_db
def test_create_event_rejects_invalid_scoring_mode(organizer_user):
    now = timezone.now()
    with pytest.raises(CTFValidationError) as exc:
        create_event(
            organizer_user,
            {
                "name": "Bad Mode",
                "event_start": now + timedelta(days=1),
                "event_end": now + timedelta(days=1, hours=8),
                "scoring_mode": "dynamic",
            },
        )
    assert exc.value.details["scoring_mode"] == "dynamic"


@pytest.mark.django_db
def test_update_event_rejects_invalid_scoring_mode(ctf_event_draft):
    with pytest.raises(CTFValidationError):
        update_event(ctf_event_draft.id, {"scoring_mode": "nope"})


# ---------------------------------------------------------------------------
# Organizer visibility surfaces
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_detail_payload_exposes_scoring_mode(ctf_event):
    payload = _event_detail_payload(ctf_event)
    assert payload["scoring_mode"] == ctf_event.scoring_mode == "standard"


def test_event_form_includes_scoring_mode():
    assert "scoring_mode" in CTFEventForm().fields
