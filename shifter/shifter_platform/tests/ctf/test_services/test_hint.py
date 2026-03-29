"""Tests for CTF progressive hint service (CTF-003) and hint purchase (CTF-304).

Integration-style tests using real DB objects.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus, ParticipantStatus
from ctf.exceptions import CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFEvent, CTFHint, CTFParticipant
from ctf.services.hint import (
    add_hint,
    get_hints,
    get_total_hint_penalty,
    get_unlocked_hints,
    remove_hint,
    use_hint,
)


@pytest.fixture
def draft_event(db, organizer_user):
    return CTFEvent.objects.create(
        name="Hint Test Event",
        created_by=organizer_user,
        status=EventStatus.DRAFT.value,
        event_start=timezone.now() + timedelta(days=1),
        event_end=timezone.now() + timedelta(days=1, hours=8),
        scenario_id="basic",
    )


@pytest.fixture
def active_event(db, organizer_user):
    return CTFEvent.objects.create(
        name="Active Hint Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
    )


@pytest.fixture
def challenge(db, draft_event):
    return CTFChallenge.objects.create(
        event=draft_event,
        name="Hint Challenge",
        description="Test",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$placeholder_hint",
    )


@pytest.fixture
def active_challenge(db, active_event):
    return CTFChallenge.objects.create(
        event=active_event,
        name="Active Hint Challenge",
        description="Test",
        category=ChallengeCategory.WEB.value,
        points=200,
        difficulty=ChallengeDifficulty.MEDIUM.value,
        flag_hash="$2b$12$placeholder_active",
    )


@pytest.fixture
def participant(db, active_event, participant_user):
    return CTFParticipant.objects.create(
        event=active_event,
        user=participant_user,
        email=participant_user.email,
        name="Hint User",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


@pytest.mark.django_db
class TestHintCRUD:
    """Tests for hint add/remove."""

    def test_add_hint(self, challenge):
        hint = add_hint(challenge.id, {"text": "Look at the source code", "penalty": 10, "order": 0})
        assert hint.text == "Look at the source code"
        assert hint.penalty == 10
        assert hint.order == 0

    def test_add_hint_requires_text(self, challenge):
        with pytest.raises(CTFValidationError, match="text is required"):
            add_hint(challenge.id, {"text": "", "penalty": 10})

    def test_remove_hint(self, challenge):
        hint = add_hint(challenge.id, {"text": "Remove me", "penalty": 5})
        remove_hint(hint.id)
        assert CTFHint.objects.filter(pk=hint.id, deleted_at__isnull=True).count() == 0

    def test_get_hints_ordered(self, challenge):
        add_hint(challenge.id, {"text": "Second", "penalty": 10, "order": 1})
        add_hint(challenge.id, {"text": "First", "penalty": 5, "order": 0})
        hints = list(get_hints(challenge.id))
        assert hints[0].text == "First"
        assert hints[1].text == "Second"


@pytest.mark.django_db
class TestHintUsage:
    """Tests for progressive hint unlocking."""

    def test_use_hint_unlocks(self, active_challenge, participant):
        hint = CTFHint.objects.create(challenge=active_challenge, text="Hint 1", penalty=10, order=0)
        result = use_hint(participant.id, hint.id)
        assert result["text"] == "Hint 1"
        assert result["penalty"] == 10
        assert not result["already_unlocked"]

    def test_use_hint_idempotent(self, active_challenge, participant):
        hint = CTFHint.objects.create(challenge=active_challenge, text="Hint 1", penalty=10, order=0)
        use_hint(participant.id, hint.id)
        result = use_hint(participant.id, hint.id)
        assert result["already_unlocked"]

    def test_use_hint_sequential_order(self, active_challenge, participant):
        CTFHint.objects.create(challenge=active_challenge, text="Hint 1", penalty=5, order=0)
        hint2 = CTFHint.objects.create(challenge=active_challenge, text="Hint 2", penalty=10, order=1)

        with pytest.raises(CTFValidationError, match="Must unlock hint"):
            use_hint(participant.id, hint2.id)

    def test_use_hint_event_not_active(self, challenge, participant_user):
        """Cannot use hint when event is not active (draft event)."""
        hint = CTFHint.objects.create(challenge=challenge, text="Draft hint", penalty=5, order=0)
        # Create participant in the draft event
        p = CTFParticipant.objects.create(
            event=challenge.event,
            user=participant_user,
            email=participant_user.email,
            name="Draft User",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        with pytest.raises(CTFStateError, match="not active"):
            use_hint(p.id, hint.id)

    def test_get_total_hint_penalty(self, active_challenge, participant):
        h1 = CTFHint.objects.create(challenge=active_challenge, text="H1", penalty=15, order=0)
        h2 = CTFHint.objects.create(challenge=active_challenge, text="H2", penalty=25, order=1)

        use_hint(participant.id, h1.id)
        assert get_total_hint_penalty(participant.id, active_challenge.id) == 15

        use_hint(participant.id, h2.id)
        assert get_total_hint_penalty(participant.id, active_challenge.id) == 40

    def test_total_penalty_capped_at_100(self, active_challenge, participant):
        h1 = CTFHint.objects.create(challenge=active_challenge, text="H1", penalty=60, order=0)
        h2 = CTFHint.objects.create(challenge=active_challenge, text="H2", penalty=60, order=1)

        use_hint(participant.id, h1.id)
        use_hint(participant.id, h2.id)
        assert get_total_hint_penalty(participant.id, active_challenge.id) == 100

    def test_get_unlocked_hints(self, active_challenge, participant):
        h1 = CTFHint.objects.create(challenge=active_challenge, text="H1", penalty=10, order=0)
        CTFHint.objects.create(challenge=active_challenge, text="H2", penalty=10, order=1)

        use_hint(participant.id, h1.id)
        unlocked = get_unlocked_hints(participant.id, active_challenge.id)
        assert len(unlocked) == 1
        assert unlocked[0].id == h1.id


@pytest.mark.django_db
class TestHintPurchaseContext:
    """Tests for hint cost/purchase context variables (CTF-304)."""

    @pytest.fixture
    def participant_client(self, participant):
        client = Client()
        client.force_login(participant.user)
        return client

    def test_next_hint_cost_in_context(self, participant_client, active_challenge, participant):
        """Context includes next_hint_cost with correct point deduction."""
        # 200-point challenge, 25% penalty hint = 50 pts cost
        CTFHint.objects.create(challenge=active_challenge, text="H1", penalty=25, order=0)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": active_challenge.pk})
        response = participant_client.get(url)
        assert response.status_code == 200
        assert response.context["next_hint_cost"] == 50

    def test_points_after_next_hint_in_context(self, participant_client, active_challenge, participant):
        """Context includes points_after_next_hint with correct projected value."""
        # 200-point challenge, 25% penalty = 150 pts after
        CTFHint.objects.create(challenge=active_challenge, text="H1", penalty=25, order=0)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": active_challenge.pk})
        response = participant_client.get(url)
        assert response.status_code == 200
        assert response.context["points_after_next_hint"] == 150

    def test_penalty_warning_false_when_below_100(self, participant_client, active_challenge, participant):
        """penalty_warning is False when projected penalty < 100%."""
        CTFHint.objects.create(challenge=active_challenge, text="H1", penalty=50, order=0)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": active_challenge.pk})
        response = participant_client.get(url)
        assert response.context["penalty_warning"] is False

    def test_penalty_warning_true_at_100(self, participant_client, active_challenge, participant):
        """penalty_warning is True when projected penalty reaches 100%."""
        h1 = CTFHint.objects.create(challenge=active_challenge, text="H1", penalty=60, order=0)
        CTFHint.objects.create(challenge=active_challenge, text="H2", penalty=60, order=1)
        # Unlock first hint so next hint pushes total to 120 (capped at 100)
        use_hint(participant.id, h1.id)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": active_challenge.pk})
        response = participant_client.get(url)
        assert response.context["penalty_warning"] is True
        # Points floor at 1
        assert response.context["points_after_next_hint"] == 1

    def test_no_hints_gives_zero_cost(self, participant_client, active_challenge, participant):
        """When no hints exist, cost variables are zero/default."""
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": active_challenge.pk})
        response = participant_client.get(url)
        assert response.context["next_hint_cost"] == 0
        assert response.context["points_after_next_hint"] == active_challenge.points
        assert response.context["penalty_warning"] is False

    def test_zero_penalty_hint_gives_zero_cost(self, participant_client, active_challenge, participant):
        """A hint with 0% penalty shows zero cost."""
        CTFHint.objects.create(challenge=active_challenge, text="Free hint", penalty=0, order=0)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": active_challenge.pk})
        response = participant_client.get(url)
        assert response.context["next_hint_cost"] == 0
        assert response.context["points_after_next_hint"] == active_challenge.points
