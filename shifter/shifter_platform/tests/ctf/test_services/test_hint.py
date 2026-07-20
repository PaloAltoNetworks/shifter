"""Tests for CTF progressive hint service (CTF-003) and hint purchase (CTF-304).

Integration-style tests using real DB objects.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from ctf.enums import (
    ChallengeCategory,
    ChallengeDifficulty,
    ChallengeVisibility,
    EventStatus,
    ParticipantStatus,
)
from ctf.exceptions import CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFEvent, CTFHint, CTFHintUsage, CTFParticipant
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
        hint = add_hint(
            challenge.id,
            {"text": "Look at the source code", "penalty": 10, "order": 0},
            actor_id=challenge.event.created_by_id,
        )
        assert hint.text == "Look at the source code"
        assert hint.penalty == 10
        assert hint.order == 0

    def test_add_hint_requires_text(self, challenge):
        with pytest.raises(CTFValidationError, match="text is required"):
            add_hint(challenge.id, {"text": "", "penalty": 10}, actor_id=challenge.event.created_by_id)

    def test_remove_hint(self, challenge):
        hint = add_hint(challenge.id, {"text": "Remove me", "penalty": 5}, actor_id=challenge.event.created_by_id)
        remove_hint(hint.id, actor_id=hint.challenge.event.created_by_id)
        # CTFHint.objects (SoftDeleteManager) excludes deleted rows by default.
        assert CTFHint.objects.filter(pk=hint.id).count() == 0

    def test_get_hints_ordered(self, challenge):
        add_hint(challenge.id, {"text": "Second", "penalty": 10, "order": 1}, actor_id=challenge.event.created_by_id)
        add_hint(challenge.id, {"text": "First", "penalty": 5, "order": 0}, actor_id=challenge.event.created_by_id)
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
        # Points floor at 0 (CTF-203, issue #519).
        assert response.context["points_after_next_hint"] == 0

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

    def test_marginal_cost_with_prior_hints(self, participant_client, active_challenge, participant):
        """next_hint_cost reflects marginal loss, not raw single-hint deduction.

        200pt challenge. Hint 1 = 60%, hint 2 = 60%.
        After hint 1: penalty 60%, value = 200 - 120 = 80.
        After hint 2: penalty 120% capped to 100%, value = 0 (CTF-203 floor).
        Marginal cost of hint 2 = 80 - 0 = 80 (not 120).
        """
        h1 = CTFHint.objects.create(challenge=active_challenge, text="H1", penalty=60, order=0)
        CTFHint.objects.create(challenge=active_challenge, text="H2", penalty=60, order=1)
        use_hint(participant.id, h1.id)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": active_challenge.pk})
        response = participant_client.get(url)
        assert response.context["next_hint_cost"] == 80
        assert response.context["points_after_next_hint"] == 0


# ============================================================================
# Issue #769 — hint unlock must enforce the same availability policy as
# flag submission (event time window, challenge release / visibility,
# prerequisites). Persistence on CTFHintUsage is locked down here too —
# the issue body's "never persisted" claim is stale; this regression
# test stops it from drifting back.
# ============================================================================


@pytest.mark.django_db
class TestHintAvailabilityPolicy:
    """Hint unlocks must mirror flag-submission availability checks.

    Hints leak the solution path; they must not be cheaper to obtain than
    flag submission.
    """

    def test_use_hint_rejects_when_event_outside_window(self, active_event, participant):
        """Active event whose competition window ended still rejects hint unlock."""
        # Push window into the past — event status remains ACTIVE but the
        # competition window has closed (mirrors submit_flag's CTF-702 check).
        active_event.event_start = timezone.now() - timedelta(days=2)
        active_event.event_end = timezone.now() - timedelta(days=1)
        active_event.save(update_fields=["event_start", "event_end"])

        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Window Test",
            description="x",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$placeholder_window",
        )
        hint = CTFHint.objects.create(challenge=challenge, text="x", penalty=5, order=0)

        with pytest.raises(CTFStateError, match="competition window"):
            use_hint(participant.id, hint.id)

    def test_use_hint_rejects_when_challenge_hidden(self, active_challenge, participant):
        active_challenge.visibility = ChallengeVisibility.HIDDEN.value
        active_challenge.save(update_fields=["visibility"])
        hint = CTFHint.objects.create(challenge=active_challenge, text="x", penalty=5, order=0)

        with pytest.raises(CTFStateError, match=r"not available|hidden"):
            use_hint(participant.id, hint.id)

    def test_use_hint_rejects_when_challenge_locked(self, active_challenge, participant):
        active_challenge.visibility = ChallengeVisibility.LOCKED.value
        active_challenge.save(update_fields=["visibility"])
        hint = CTFHint.objects.create(challenge=active_challenge, text="x", penalty=5, order=0)

        with pytest.raises(CTFStateError, match="locked"):
            use_hint(participant.id, hint.id)

    def test_use_hint_rejects_when_challenge_unreleased(self, active_event, participant):
        """Future release_time keeps the challenge from being unlockable yet."""
        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Delayed",
            description="x",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$placeholder_delayed",
            release_time=timezone.now() + timedelta(hours=2),
        )
        hint = CTFHint.objects.create(challenge=challenge, text="x", penalty=5, order=0)

        with pytest.raises(CTFStateError, match="released"):
            use_hint(participant.id, hint.id)

    def test_use_hint_rejects_when_prerequisites_not_met(self, active_event, participant):
        from ctf.models import CTFChallengePrerequisite

        gating = CTFChallenge.objects.create(
            event=active_event,
            name="Gating",
            description="x",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$placeholder_gating",
        )
        gated = CTFChallenge.objects.create(
            event=active_event,
            name="Gated",
            description="x",
            category=ChallengeCategory.WEB.value,
            points=200,
            difficulty=ChallengeDifficulty.MEDIUM.value,
            flag_hash="$2b$12$placeholder_gated",
        )
        CTFChallengePrerequisite.objects.create(challenge=gated, required_challenge=gating)
        hint = CTFHint.objects.create(challenge=gated, text="x", penalty=5, order=0)

        with pytest.raises(CTFStateError, match=r"[Pp]rerequisites"):
            use_hint(participant.id, hint.id)

    def test_use_hint_persists_usage(self, active_challenge, participant):
        """Lock-down regression: a successful unlock writes a CTFHintUsage row.

        The issue body claimed hint usage was never persisted; this test stops
        that drifting back. Without the row, get_total_hint_penalty would
        return 0 and submit_flag would never apply the penalty.
        """
        hint = CTFHint.objects.create(challenge=active_challenge, text="real hint", penalty=20, order=0)

        use_hint(participant.id, hint.id)

        assert CTFHintUsage.objects.filter(participant=participant, hint=hint).exists()

    def test_use_hint_rejects_when_expected_challenge_id_mismatches(self, active_event, participant):
        """Service-level enforcement of the route/body coherence guard
        (codex review finding for #769). Even when called directly from a
        non-HTTP caller, `use_hint` must refuse to unlock a hint that
        belongs to a different challenge than the caller intended.
        """
        # Two challenges in the same event; the participant intends to
        # interact with `intended` but the supplied hint belongs to `other`.
        intended = CTFChallenge.objects.create(
            event=active_event,
            name="Intended",
            description="x",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$placeholder_intended",
        )
        other = CTFChallenge.objects.create(
            event=active_event,
            name="Other",
            description="x",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$placeholder_other",
        )
        hint_for_other = CTFHint.objects.create(challenge=other, text="x", penalty=5, order=0)

        with pytest.raises(CTFValidationError, match=r"not belong"):
            use_hint(participant.id, hint_for_other.id, expected_challenge_id=intended.id)

        # And no usage row was written — refusal is total, not partial.
        assert not CTFHintUsage.objects.filter(participant=participant, hint=hint_for_other).exists()


@pytest.mark.django_db
class TestSubmitFlagAppliesHintPenalty:
    """Lock-down regression for issue #769: scoring path through
    get_total_hint_penalty must actually deduct unlocked hints' penalty.

    Issue body claimed "the advertised penalty is never applied"; today
    submit_flag already calls get_total_hint_penalty. This test guards the
    integration so a future refactor can't silently break it.
    """

    def test_submit_flag_applies_hint_penalty_after_unlock(self, active_event, participant_user):
        from ctf.services.challenge import hash_flag
        from ctf.services.submission import submit_flag

        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Penalty Test",
            description="x",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash=hash_flag("FLAG{penalty_test}"),
        )
        # The hint penalty machinery is on CTFHint + CTFHintUsage.
        CTFHint.objects.create(challenge=challenge, text="The flag", penalty=25, order=0)
        # The active_event fixture's owner is the organizer; create a fresh
        # participant for THIS event — `participant` fixture is bound to a
        # different active_event in this file.
        p = CTFParticipant.objects.create(
            event=active_event,
            user=participant_user,
            email=participant_user.email,
            name="Penalty User",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        # Unlock the hint, then submit the correct flag.
        hint = CTFHint.objects.get(challenge=challenge, order=0)
        use_hint(p.id, hint.id)
        submission = submit_flag(p.id, challenge.id, "FLAG{penalty_test}")

        # 25% penalty on a 100pt challenge = 75 awarded.
        assert submission.is_correct is True
        assert submission.points_awarded == 75
