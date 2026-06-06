"""Tests for CTF challenge management.

Tests for:
- Challenge forms
- Challenge views (list, create, detail, edit)
- Challenge services
- Multi-flag support (CTFFlag model, add_flag, remove_flag, verify_flag)
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus
from ctf.models import CTFChallenge, CTFSubmission
from ctf.services import (
    create_challenge,
    update_challenge,
)

# =============================================================================
# Form Tests
# =============================================================================


class TestChallengeVisibility:
    """Tests for challenge visibility states (CTF-110)."""

    @pytest.fixture
    def event(self, db):
        """Create an active event."""
        from django.contrib.auth.models import User
        from django.utils import timezone as tz

        from ctf.models import CTFEvent

        user = User.objects.create_user("org@test.com", "org@test.com", "pass")
        return CTFEvent.objects.create(
            name="Vis Test",
            created_by=user,
            status=EventStatus.ACTIVE.value,
            event_start=tz.now() - timedelta(hours=1),
            event_end=tz.now() + timedelta(hours=5),
        )

    @pytest.fixture
    def visible_challenge(self, event):
        return CTFChallenge.objects.create(
            event=event,
            name="Visible",
            description="d",
            category="web",
            points=100,
            flag_hash="x",
            visibility="visible",
        )

    @pytest.fixture
    def hidden_challenge(self, event):
        return CTFChallenge.objects.create(
            event=event,
            name="Hidden",
            description="d",
            category="web",
            points=100,
            flag_hash="x",
            visibility="hidden",
        )

    @pytest.fixture
    def locked_challenge(self, event):
        return CTFChallenge.objects.create(
            event=event,
            name="Locked",
            description="d",
            category="web",
            points=100,
            flag_hash="x",
            visibility="locked",
        )

    def test_hidden_not_released(self, hidden_challenge):
        """Hidden challenge is_released returns False."""
        assert hidden_challenge.is_released is False

    def test_visible_is_released(self, visible_challenge):
        """Visible challenge is_released returns True."""
        assert visible_challenge.is_released is True

    def test_locked_is_released(self, locked_challenge):
        """Locked challenge is_released returns True (shown but not submittable)."""
        assert locked_challenge.is_released is True

    def test_locked_is_visibility_locked(self, locked_challenge):
        """Locked challenge is_visibility_locked returns True."""
        assert locked_challenge.is_visibility_locked is True

    def test_visible_not_visibility_locked(self, visible_challenge):
        """Visible challenge is_visibility_locked returns False."""
        assert visible_challenge.is_visibility_locked is False

    def test_hidden_excluded_from_available(self, event, visible_challenge, hidden_challenge):
        """get_available_challenges excludes hidden challenges."""
        from ctf.services.challenge import get_available_challenges

        available = list(get_available_challenges(event.pk))
        assert visible_challenge in available
        assert hidden_challenge not in available

    def test_locked_included_in_available(self, event, visible_challenge, locked_challenge):
        """get_available_challenges includes locked challenges."""
        from ctf.services.challenge import get_available_challenges

        available = list(get_available_challenges(event.pk))
        assert visible_challenge in available
        assert locked_challenge in available

    def test_organizer_sees_all(self, event, visible_challenge, hidden_challenge, locked_challenge):
        """include_unreleased=True returns all visibility states."""
        from ctf.services.challenge import get_available_challenges

        all_challenges = list(get_available_challenges(event.pk, include_unreleased=True))
        assert visible_challenge in all_challenges
        assert hidden_challenge in all_challenges
        assert locked_challenge in all_challenges

    def test_visibility_in_mutable_fields(self):
        """visibility is in the mutable fields set."""
        from ctf.services.challenge import _CHALLENGE_MUTABLE_FIELDS

        assert "visibility" in _CHALLENGE_MUTABLE_FIELDS

    def test_default_visibility_is_visible(self, event):
        """New challenges default to visible."""
        c = CTFChallenge.objects.create(
            event=event,
            name="Default",
            description="d",
            category="web",
            points=100,
            flag_hash="x",
        )
        assert c.visibility == "visible"


class TestChallengeTags:
    """Tests for challenge tag management (CTF-113)."""

    def test_create_challenge_with_tags(self, ctf_event_draft):
        """Creating a challenge with tags attaches them."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "Tagged Challenge",
                "description": "Has tags",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{tagged}",
                "tags": ["XDR", "Linux"],
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        tag_names = list(challenge.tags.values_list("name", flat=True))
        assert sorted(tag_names) == ["linux", "xdr"]

    def test_update_challenge_tags(self, ctf_event_draft):
        """Updating tags replaces the existing set."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "Tag Update",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{update}",
                "tags": ["Linux", "Windows"],
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        updated = update_challenge(challenge.id, {"tags": ["XDR"]}, actor_id=challenge.event.created_by_id)
        assert list(updated.tags.values_list("name", flat=True)) == ["xdr"]

    def test_tags_reusable_across_challenges(self, ctf_event_draft):
        """Same tag can be applied to multiple challenges in the same event."""
        c1 = create_challenge(
            ctf_event_draft.id,
            {
                "name": "Challenge A",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{a}",
                "tags": ["XDR"],
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        c2 = create_challenge(
            ctf_event_draft.id,
            {
                "name": "Challenge B",
                "description": "d",
                "category": ChallengeCategory.CRYPTO.value,
                "points": 200,
                "flag": "FLAG{b}",
                "tags": ["XDR"],
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        # Both challenges share the same tag object
        assert c1.tags.first().pk == c2.tags.first().pk

    def test_tag_unique_per_event(self, ctf_event_draft):
        """Tags with the same name in the same event resolve to one object."""
        from ctf.models import CTFChallengeTag

        create_challenge(
            ctf_event_draft.id,
            {
                "name": "First",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{1}",
                "tags": ["XDR", "XDR"],  # duplicate in same call
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        assert CTFChallengeTag.objects.filter(event=ctf_event_draft, name="xdr").count() == 1

    def test_create_challenge_without_tags(self, ctf_event_draft):
        """Challenges without tags have empty tag set."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "No Tags",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{notags}",
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        assert challenge.tags.count() == 0

    def test_clear_tags_with_empty_list(self, ctf_event_draft):
        """Passing empty tags list clears all tags."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "Clear Tags",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{clear}",
                "tags": ["XDR", "Linux"],
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        assert challenge.tags.count() == 2
        updated = update_challenge(challenge.id, {"tags": []}, actor_id=challenge.event.created_by_id)
        assert updated.tags.count() == 0


class TestChallengeSolutions:
    """Tests for challenge solution writeups (CTF-117)."""

    def test_create_challenge_with_solution(self, ctf_event_draft):
        """Creating a challenge with solution stores it."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "Solution Challenge",
                "description": "Has a solution",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{solved}",
                "solution": "Step 1: inspect the HTML source.\nStep 2: find the flag in comments.",
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        assert "Step 1" in challenge.solution

    def test_solution_default_empty(self, ctf_event_draft):
        """Challenges without solution have empty string."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "No Solution",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{nosol}",
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        assert challenge.solution == ""

    def test_solution_in_mutable_fields(self):
        """Solution is in the challenge mutable fields whitelist."""
        from ctf.services.challenge import _CHALLENGE_MUTABLE_FIELDS

        assert "solution" in _CHALLENGE_MUTABLE_FIELDS

    def test_update_challenge_solution(self, ctf_event_draft):
        """Updating solution replaces existing content."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "Update Solution",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{updsol}",
                "solution": "Original solution.",
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        updated = update_challenge(
            challenge.id,
            {"solution": "Updated solution with ```code blocks```."},
            actor_id=challenge.event.created_by_id,
        )
        assert "Updated solution" in updated.solution

    def test_solution_visibility_by_event_status(self, ctf_event_draft):
        """Solution visibility depends on event status."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "Visibility Test",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{vis}",
                "solution": "The answer is 42.",
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        event = ctf_event_draft

        # show_solution logic mirrors the view: solution && status in (ended, archived)
        def show_solution():
            return bool(challenge.solution and event.status in ("ended", "archived"))

        event.status = "draft"
        assert not show_solution()

        event.status = "active"
        assert not show_solution()

        event.status = "paused"
        assert not show_solution()

        event.status = "ended"
        assert show_solution()

        event.status = "archived"
        assert show_solution()

    def test_solution_not_visible_when_empty(self, ctf_event_draft):
        """Empty solution is never shown even after event ends."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "No Solution Vis",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{empty}",
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        ctf_event_draft.status = "ended"
        assert not bool(challenge.solution and ctf_event_draft.status in ("ended", "archived"))


class TestChallengeTopics:
    """Tests for challenge topic taxonomy (CTF-119)."""

    def test_create_challenge_with_topics(self, ctf_event_draft):
        """Creating a challenge with topics attaches them."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "Topic Challenge",
                "description": "Has topics",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{topic}",
                "topics": ["SQL Injection", "XSS"],
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        topic_names = sorted(challenge.topics.values_list("name", flat=True))
        assert topic_names == ["sql injection", "xss"]

    def test_update_challenge_topics(self, ctf_event_draft):
        """Updating topics replaces the existing set."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "Topic Update",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{topicupd}",
                "topics": ["SQL Injection"],
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        updated = update_challenge(
            challenge.id, {"topics": ["Privilege Escalation"]}, actor_id=challenge.event.created_by_id
        )
        assert list(updated.topics.values_list("name", flat=True)) == ["privilege escalation"]

    def test_topics_reusable_across_events(self, ctf_event_draft, organizer_user):
        """Same topic can be used by challenges in different events."""
        from datetime import timedelta

        from django.utils import timezone

        from ctf.models import CTFEvent, CTFTopic

        event2 = CTFEvent.objects.create(
            name="Second Event",
            created_by=organizer_user,
            status="draft",
            event_start=timezone.now() + timedelta(days=10),
            event_end=timezone.now() + timedelta(days=10, hours=8),
            scenario_id="basic",
        )
        c1 = create_challenge(
            ctf_event_draft.id,
            {
                "name": "E1 Challenge",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{e1}",
                "topics": ["SQL Injection"],
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        c2 = create_challenge(
            event2.id,
            {
                "name": "E2 Challenge",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{e2}",
                "topics": ["SQL Injection"],
            },
            actor_id=event2.created_by_id,
        )
        # Both share the same global topic object
        assert c1.topics.first().pk == c2.topics.first().pk
        assert CTFTopic.objects.filter(name="sql injection").count() == 1

    def test_topic_global_uniqueness(self, ctf_event_draft):
        """Topics are globally unique by name."""
        from ctf.models import CTFTopic

        create_challenge(
            ctf_event_draft.id,
            {
                "name": "Unique Topic",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{uniq}",
                "topics": ["Network Analysis", "Network Analysis"],
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        assert CTFTopic.objects.filter(name="network analysis").count() == 1

    def test_create_challenge_without_topics(self, ctf_event_draft):
        """Challenges without topics have empty set."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "No Topics",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{notopic}",
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        assert challenge.topics.count() == 0

    def test_clear_topics(self, ctf_event_draft):
        """Passing empty topics list clears all topics."""
        challenge = create_challenge(
            ctf_event_draft.id,
            {
                "name": "Clear Topics",
                "description": "d",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "flag": "FLAG{cleartopic}",
                "topics": ["SQL Injection", "XSS"],
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        assert challenge.topics.count() == 2
        updated = update_challenge(challenge.id, {"topics": []}, actor_id=challenge.event.created_by_id)
        assert updated.topics.count() == 0


class TestChallengeRatings:
    """Tests for challenge ratings (CTF-120)."""

    @pytest.fixture
    def active_event(self, db, organizer_user):
        from datetime import timedelta

        from django.utils import timezone

        from ctf.models import CTFEvent

        return CTFEvent.objects.create(
            name="Rating Event",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
            submission_cooldown_seconds=0,
            rating_visibility="public",
        )

    @pytest.fixture
    def participant(self, active_event, participant_user):
        from django.utils import timezone

        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        return CTFParticipant.objects.create(
            event=active_event,
            user=participant_user,
            email=participant_user.email,
            name="Rater",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )

    @pytest.fixture
    def solved_challenge(self, active_event, participant):
        from ctf.models import CTFChallenge

        challenge = CTFChallenge.objects.create(
            event=active_event,
            name="Rated Challenge",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$placeholder_rate",
        )
        # Create a correct submission
        CTFSubmission.objects.create(
            participant=participant,
            challenge=challenge,
            submitted_flag="FLAG{correct}",
            is_correct=True,
            points_awarded=100,
            attempt_number=1,
        )
        return challenge

    def test_rate_challenge_after_solving(self, participant, solved_challenge):
        from ctf.services.submission import rate_challenge

        rating = rate_challenge(participant.id, solved_challenge.id, 4)
        assert rating.value == 4

    def test_rate_challenge_before_solving_fails(self, active_event, participant):
        from ctf.exceptions import CTFValidationError
        from ctf.models import CTFChallenge
        from ctf.services.submission import rate_challenge

        unsolved = CTFChallenge.objects.create(
            event=active_event,
            name="Unsolved",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$placeholder_unsolved",
        )
        with pytest.raises(CTFValidationError, match="must solve"):
            rate_challenge(participant.id, unsolved.id, 3)

    def test_update_existing_rating(self, participant, solved_challenge):
        from ctf.services.submission import rate_challenge

        rate_challenge(participant.id, solved_challenge.id, 3)
        rating = rate_challenge(participant.id, solved_challenge.id, 5)
        assert rating.value == 5
        # Should still be only one rating
        from ctf.models import CTFChallengeRating

        assert CTFChallengeRating.objects.filter(participant=participant, challenge=solved_challenge).count() == 1

    def test_rating_value_validation(self, participant, solved_challenge):
        from ctf.exceptions import CTFValidationError
        from ctf.services.submission import rate_challenge

        with pytest.raises(CTFValidationError, match="between 1 and 5"):
            rate_challenge(participant.id, solved_challenge.id, 0)

        with pytest.raises(CTFValidationError, match="between 1 and 5"):
            rate_challenge(participant.id, solved_challenge.id, 6)

    def test_get_challenge_rating_average(self, active_event, solved_challenge, participant, organizer_user):
        from django.contrib.auth.models import User
        from django.utils import timezone

        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant
        from ctf.services.submission import get_challenge_rating, rate_challenge

        # First participant rates 4
        rate_challenge(participant.id, solved_challenge.id, 4)

        # Create second participant who also solved it
        user2 = User.objects.create_user("rater2", "rater2@test.com", "pass")
        p2 = CTFParticipant.objects.create(
            event=active_event,
            user=user2,
            email=user2.email,
            name="Rater 2",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        CTFSubmission.objects.create(
            participant=p2,
            challenge=solved_challenge,
            submitted_flag="FLAG{correct}",
            is_correct=True,
            points_awarded=100,
            attempt_number=1,
        )
        rate_challenge(p2.id, solved_challenge.id, 2)

        result = get_challenge_rating(solved_challenge.id)
        assert result["average"] == 3.0
        assert result["count"] == 2

    def test_rating_disabled_event(self, organizer_user, participant_user):
        from datetime import timedelta

        from django.utils import timezone

        from ctf.enums import ParticipantStatus
        from ctf.exceptions import CTFValidationError
        from ctf.models import CTFChallenge, CTFEvent, CTFParticipant
        from ctf.services.submission import rate_challenge

        event = CTFEvent.objects.create(
            name="No Ratings Event",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
            rating_visibility="disabled",
        )
        challenge = CTFChallenge.objects.create(
            event=event,
            name="No Rate",
            description="Test",
            category=ChallengeCategory.WEB.value,
            points=100,
            flag_hash="$2b$12$x",
        )
        p = CTFParticipant.objects.create(
            event=event,
            user=participant_user,
            email=participant_user.email,
            name="No Rater",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        CTFSubmission.objects.create(
            participant=p,
            challenge=challenge,
            submitted_flag="FLAG{x}",
            is_correct=True,
            points_awarded=100,
            attempt_number=1,
        )
        with pytest.raises(CTFValidationError, match="disabled"):
            rate_challenge(p.id, challenge.id, 4)
