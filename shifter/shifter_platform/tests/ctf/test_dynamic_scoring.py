"""Dynamic/decay scoring behavior (CTF-202, issue #641)."""

from __future__ import annotations

import pytest

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus, ScoringMode
from ctf.models import CTFChallenge, CTFEvent
from ctf.services.challenge import add_flag
from ctf.services.scoring._strategy import dynamic_challenge_value
from ctf.services.submission import submit_flag

pytestmark = pytest.mark.django_db


class TestDynamicValueMath:
    """Pure decay-curve behavior."""

    def _challenge(self, **overrides):
        from unittest.mock import MagicMock

        challenge = MagicMock(spec=CTFChallenge)
        challenge.points = overrides.get("points", 500)
        challenge.minimum_points = overrides.get("minimum_points", 100)
        challenge.decay_function = overrides.get("decay_function", "linear")
        challenge.decay_solve_count = overrides.get("decay_solve_count", 10)
        return challenge

    def test_no_decay_when_disabled(self):
        challenge = self._challenge(decay_solve_count=0)
        assert dynamic_challenge_value(challenge, 50) == 500

    def test_linear_decay_steps_to_minimum(self):
        challenge = self._challenge()
        assert dynamic_challenge_value(challenge, 0) == 500
        assert dynamic_challenge_value(challenge, 5) == 300
        assert dynamic_challenge_value(challenge, 10) == 100
        assert dynamic_challenge_value(challenge, 25) == 100

    def test_logarithmic_decay_drops_fastest_early(self):
        challenge = self._challenge(decay_function="logarithmic")
        first = dynamic_challenge_value(challenge, 1)
        second = dynamic_challenge_value(challenge, 2)
        assert first < 500
        assert second < first
        assert dynamic_challenge_value(challenge, 10) == 100
        assert dynamic_challenge_value(challenge, 40) == 100

    def test_minimum_never_exceeds_initial(self):
        challenge = self._challenge(points=100, minimum_points=400)
        assert dynamic_challenge_value(challenge, 3) == 100


class TestDynamicScoringEndToEnd:
    """Retroactive re-pricing through the real submit path."""

    @pytest.fixture
    def dynamic_event(self, organizer_user):
        from datetime import timedelta

        from django.utils import timezone

        return CTFEvent.objects.create(
            name="Dynamic Event",
            description="decay",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
            scoring_mode=ScoringMode.DYNAMIC.value,
        )

    def _challenge(self, event):
        challenge = CTFChallenge.objects.create(
            event=event,
            name="Decaying Challenge",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=500,
            minimum_points=100,
            decay_function="linear",
            decay_solve_count=4,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        add_flag(challenge.pk, {"flag": "FLAG{decay}"}, actor_id=event.created_by_id)
        return challenge

    def _participant(self, event, index):
        from ctf.services.participant import invite_participant

        participant = invite_participant(
            event_id=event.pk,
            email=f"decay-player-{index}@test.com",
            name=f"Decay Player {index}",
        )
        from django.utils import timezone

        participant.registered_at = timezone.now()
        participant.status = "active"
        participant.save(update_fields=["registered_at", "status", "updated_at"])
        return participant

    def test_new_solve_reprices_earlier_solvers(self, dynamic_event):
        challenge = self._challenge(dynamic_event)
        first = self._participant(dynamic_event, 1)
        second = self._participant(dynamic_event, 2)

        first_submission = submit_flag(first.pk, challenge.pk, "FLAG{decay}")
        assert first_submission.points_awarded == 400  # 500 - (400/4)*1

        second_submission = submit_flag(second.pk, challenge.pk, "FLAG{decay}")
        assert second_submission.points_awarded == 300

        # Retroactive: the first solver now holds the same decayed base value.
        first_submission.refresh_from_db()
        assert first_submission.points_awarded == 300
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.cached_score == 300
        assert second.cached_score == 300

    def test_value_floors_at_minimum(self, dynamic_event):
        challenge = self._challenge(dynamic_event)
        submissions = []
        for index in range(1, 7):
            participant = self._participant(dynamic_event, index)
            submissions.append(submit_flag(participant.pk, challenge.pk, "FLAG{decay}"))
        for submission in submissions:
            submission.refresh_from_db()
            assert submission.points_awarded == 100

    def test_standard_events_unaffected(self, organizer_user):
        from datetime import timedelta

        from django.utils import timezone

        event = CTFEvent.objects.create(
            name="Standard Event",
            description="s",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
        )
        challenge = self._challenge(event)
        first = self._participant(event, 1)
        second = self._participant(event, 2)
        s1 = submit_flag(first.pk, challenge.pk, "FLAG{decay}")
        s2 = submit_flag(second.pk, challenge.pk, "FLAG{decay}")
        assert s1.points_awarded == 500
        assert s2.points_awarded == 500
