"""Tests for CTF challenge prerequisites.

Covers:
- Add/remove prerequisites
- Same-event validation
- Self-reference prevention
- Circular dependency detection (BFS)
- get_available_challenges filtering by prerequisites
- submit_flag blocking on unmet prerequisites
- Cascade soft-delete when required challenge is deleted
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus
from ctf.exceptions import CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFChallengePrerequisite, CTFEvent, CTFSubmission
from ctf.services.challenge import (
    add_prerequisite,
    check_prerequisites_met,
    delete_challenge,
    get_available_challenges,
    get_dependents,
    get_prerequisites,
    remove_prerequisite,
)


@pytest.fixture
def draft_event(db, organizer_user):
    """Create a draft event with multiple challenges."""
    return CTFEvent.objects.create(
        name="Prereq Test Event",
        description="Event for prerequisite testing",
        created_by=organizer_user,
        status=EventStatus.DRAFT.value,
        event_start=timezone.now() + timedelta(days=7),
        event_end=timezone.now() + timedelta(days=7, hours=8),
        scenario_id="basic",
    )


@pytest.fixture
def challenge_a(db, draft_event):
    """First challenge (no prerequisites)."""
    return CTFChallenge.objects.create(
        event=draft_event,
        name="Challenge A",
        description="First challenge",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$hash_a",
    )


@pytest.fixture
def challenge_b(db, draft_event):
    """Second challenge."""
    return CTFChallenge.objects.create(
        event=draft_event,
        name="Challenge B",
        description="Second challenge",
        category=ChallengeCategory.CRYPTO.value,
        points=200,
        difficulty=ChallengeDifficulty.MEDIUM.value,
        flag_hash="$2b$12$hash_b",
    )


@pytest.fixture
def challenge_c(db, draft_event):
    """Third challenge."""
    return CTFChallenge.objects.create(
        event=draft_event,
        name="Challenge C",
        description="Third challenge",
        category=ChallengeCategory.FORENSICS.value,
        points=300,
        difficulty=ChallengeDifficulty.HARD.value,
        flag_hash="$2b$12$hash_c",
    )


class TestAddPrerequisite:
    """Tests for add_prerequisite."""

    def test_add_prerequisite_success(self, challenge_a, challenge_b):
        """Adding a valid prerequisite creates the link."""
        prereq = add_prerequisite(challenge_b.id, challenge_a.id)
        assert prereq.challenge_id == challenge_b.id
        assert prereq.required_challenge_id == challenge_a.id

    def test_self_reference_rejected(self, challenge_a):
        """A challenge cannot require itself."""
        with pytest.raises(CTFValidationError, match="itself"):
            add_prerequisite(challenge_a.id, challenge_a.id)

    def test_different_event_rejected(self, challenge_a, organizer_user):
        """Prerequisites must be in the same event."""
        other_event = CTFEvent.objects.create(
            name="Other Event",
            description="Different event",
            created_by=organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=timezone.now() + timedelta(days=14),
            event_end=timezone.now() + timedelta(days=14, hours=8),
            scenario_id="basic",
        )
        other_challenge = CTFChallenge.objects.create(
            event=other_event,
            name="Other Challenge",
            description="In another event",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$hash_other",
        )
        with pytest.raises(CTFValidationError, match="same event"):
            add_prerequisite(challenge_a.id, other_challenge.id)

    def test_duplicate_rejected(self, challenge_a, challenge_b):
        """Cannot add the same prerequisite twice."""
        add_prerequisite(challenge_b.id, challenge_a.id)
        with pytest.raises(CTFValidationError, match="already exists"):
            add_prerequisite(challenge_b.id, challenge_a.id)

    def test_direct_cycle_rejected(self, challenge_a, challenge_b):
        """A -> B and B -> A creates a cycle."""
        add_prerequisite(challenge_b.id, challenge_a.id)  # B requires A
        with pytest.raises(CTFValidationError, match="circular"):
            add_prerequisite(challenge_a.id, challenge_b.id)  # A requires B

    def test_indirect_cycle_rejected(self, challenge_a, challenge_b, challenge_c):
        """A -> B -> C and C -> A creates a cycle."""
        add_prerequisite(challenge_b.id, challenge_a.id)  # B requires A
        add_prerequisite(challenge_c.id, challenge_b.id)  # C requires B
        with pytest.raises(CTFValidationError, match="circular"):
            add_prerequisite(challenge_a.id, challenge_c.id)  # A requires C = cycle

    def test_non_content_modifiable_rejected(self, organizer_user):
        """Cannot add prerequisites in non-modifiable events."""
        active_event = CTFEvent.objects.create(
            name="Active Event",
            description="Active",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
        )
        ch_a = CTFChallenge.objects.create(
            event=active_event,
            name="Active A",
            description="Active challenge A",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$hash_active_a",
        )
        ch_b = CTFChallenge.objects.create(
            event=active_event,
            name="Active B",
            description="Active challenge B",
            category=ChallengeCategory.WEB.value,
            points=200,
            difficulty=ChallengeDifficulty.MEDIUM.value,
            flag_hash="$2b$12$hash_active_b",
        )
        with pytest.raises(CTFStateError):
            add_prerequisite(ch_b.id, ch_a.id)


class TestRemovePrerequisite:
    """Tests for remove_prerequisite."""

    def test_remove_prerequisite_success(self, challenge_a, challenge_b):
        """Removing a prerequisite soft-deletes it."""
        prereq = add_prerequisite(challenge_b.id, challenge_a.id)
        remove_prerequisite(prereq.id)

        # Soft-deleted — not in default queryset
        assert not CTFChallengePrerequisite.objects.filter(pk=prereq.id).exists()
        # Still in all_objects
        assert CTFChallengePrerequisite.all_objects.filter(pk=prereq.id).exists()


class TestGetPrerequisites:
    """Tests for get_prerequisites and get_dependents."""

    def test_get_prerequisites(self, challenge_a, challenge_b, challenge_c):
        """get_prerequisites returns the required challenges."""
        add_prerequisite(challenge_c.id, challenge_a.id)
        add_prerequisite(challenge_c.id, challenge_b.id)

        prereqs = get_prerequisites(challenge_c.id)
        required_ids = {p.required_challenge_id for p in prereqs}
        assert required_ids == {challenge_a.id, challenge_b.id}

    def test_get_dependents(self, challenge_a, challenge_b, challenge_c):
        """get_dependents returns challenges that depend on this one."""
        add_prerequisite(challenge_b.id, challenge_a.id)
        add_prerequisite(challenge_c.id, challenge_a.id)

        deps = get_dependents(challenge_a.id)
        dep_ids = {d.challenge_id for d in deps}
        assert dep_ids == {challenge_b.id, challenge_c.id}


class TestCheckPrerequisitesMet:
    """Tests for check_prerequisites_met."""

    def test_no_prerequisites_always_met(self, challenge_a, ctf_participant):
        """Challenge with no prerequisites is always available."""
        met, unmet = check_prerequisites_met(challenge_a.id, ctf_participant.id)
        assert met is True
        assert unmet == []

    def test_unmet_prerequisites(self, draft_event, challenge_a, challenge_b, ctf_participant):
        """Unsolved prerequisite is reported as unmet."""
        # challenge_a and challenge_b are in draft_event, ctf_participant is in ctf_event
        # Need participant in same event
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        participant = CTFParticipant.objects.create(
            event=draft_event,
            user=ctf_participant.user,
            email=ctf_participant.email,
            name="Test",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        add_prerequisite(challenge_b.id, challenge_a.id)

        met, unmet = check_prerequisites_met(challenge_b.id, participant.id)
        assert met is False
        assert len(unmet) == 1
        assert unmet[0].id == challenge_a.id

    def test_met_prerequisites(self, draft_event, challenge_a, challenge_b, participant_user):
        """Solved prerequisite is reported as met."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        participant = CTFParticipant.objects.create(
            event=draft_event,
            user=participant_user,
            email=participant_user.email,
            name="Test",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        add_prerequisite(challenge_b.id, challenge_a.id)

        # Solve challenge A
        CTFSubmission.objects.create(
            participant=participant,
            challenge=challenge_a,
            submitted_flag="FLAG{a}",
            is_correct=True,
            points_awarded=100,
            attempt_number=1,
        )

        met, unmet = check_prerequisites_met(challenge_b.id, participant.id)
        assert met is True
        assert unmet == []


class TestGetAvailableChallengesWithPrereqs:
    """Tests for get_available_challenges with participant_id filtering."""

    def test_excludes_challenges_with_unmet_prereqs(
        self, draft_event, challenge_a, challenge_b, challenge_c, participant_user
    ):
        """Challenges with unmet prerequisites are excluded when participant_id is given."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        participant = CTFParticipant.objects.create(
            event=draft_event,
            user=participant_user,
            email=participant_user.email,
            name="Test",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        # C requires A
        add_prerequisite(challenge_c.id, challenge_a.id)

        available = get_available_challenges(
            draft_event.id,
            include_unreleased=True,
            participant_id=participant.id,
        )
        available_ids = set(available.values_list("id", flat=True))

        # A and B available, C excluded (requires A which isn't solved)
        assert challenge_a.id in available_ids
        assert challenge_b.id in available_ids
        assert challenge_c.id not in available_ids

    def test_includes_challenges_after_prereq_solved(
        self, draft_event, challenge_a, challenge_b, challenge_c, participant_user
    ):
        """Solving a prerequisite makes the dependent challenge available."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        participant = CTFParticipant.objects.create(
            event=draft_event,
            user=participant_user,
            email=participant_user.email,
            name="Test",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        add_prerequisite(challenge_c.id, challenge_a.id)

        # Solve A
        CTFSubmission.objects.create(
            participant=participant,
            challenge=challenge_a,
            submitted_flag="FLAG{a}",
            is_correct=True,
            points_awarded=100,
            attempt_number=1,
        )

        available = get_available_challenges(
            draft_event.id,
            include_unreleased=True,
            participant_id=participant.id,
        )
        available_ids = set(available.values_list("id", flat=True))

        # All three available now
        assert challenge_a.id in available_ids
        assert challenge_b.id in available_ids
        assert challenge_c.id in available_ids

    def test_no_participant_id_returns_all(self, draft_event, challenge_a, challenge_b, challenge_c):
        """Without participant_id, all released challenges are returned."""
        add_prerequisite(challenge_c.id, challenge_a.id)

        available = get_available_challenges(draft_event.id, include_unreleased=True)
        available_ids = set(available.values_list("id", flat=True))

        assert {challenge_a.id, challenge_b.id, challenge_c.id} == available_ids


class TestSubmitFlagPrerequisiteBlocking:
    """Tests that submit_flag blocks on unmet prerequisites."""

    def test_submit_blocked_by_unmet_prerequisite(self, organizer_user, participant_user):
        """submit_flag raises CTFStateError when prerequisites aren't met."""
        from ctf.services.submission import submit_flag

        # Create active event with two challenges
        active_event = CTFEvent.objects.create(
            name="Active Prereq Event",
            description="Active",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
        )
        ch_a = CTFChallenge.objects.create(
            event=active_event,
            name="Prereq A",
            description="First",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$hash_a",
        )
        ch_b = CTFChallenge.objects.create(
            event=active_event,
            name="Prereq B",
            description="Second, requires A",
            category=ChallengeCategory.WEB.value,
            points=200,
            difficulty=ChallengeDifficulty.MEDIUM.value,
            flag_hash="$2b$12$hash_b",
        )

        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        participant = CTFParticipant.objects.create(
            event=active_event,
            user=participant_user,
            email=participant_user.email,
            name="Test",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )

        # Add B requires A (must be done before event goes active, but we're in test)
        CTFChallengePrerequisite.objects.create(
            challenge=ch_b,
            required_challenge=ch_a,
        )

        with pytest.raises(CTFStateError, match="Prerequisites not met"):
            submit_flag(participant.id, ch_b.id, "FLAG{anything}")


class TestDeleteChallengeCascadePrereqs:
    """Tests that deleting a required challenge cascades to prerequisites."""

    def test_soft_delete_cascades_to_prerequisite_links(self, challenge_a, challenge_b, challenge_c):
        """Deleting a required challenge soft-deletes prerequisite links."""
        prereq_b = add_prerequisite(challenge_b.id, challenge_a.id)
        prereq_c = add_prerequisite(challenge_c.id, challenge_a.id)

        delete_challenge(challenge_a.id)

        # Prerequisite links should be soft-deleted
        assert not CTFChallengePrerequisite.objects.filter(pk=prereq_b.id).exists()
        assert not CTFChallengePrerequisite.objects.filter(pk=prereq_c.id).exists()
        # But still exist in all_objects
        assert CTFChallengePrerequisite.all_objects.filter(pk=prereq_b.id).exists()
        assert CTFChallengePrerequisite.all_objects.filter(pk=prereq_c.id).exists()
