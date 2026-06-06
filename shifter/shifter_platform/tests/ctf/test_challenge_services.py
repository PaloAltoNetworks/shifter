"""Tests for CTF challenge management.

Tests for:
- Challenge forms
- Challenge views (list, create, detail, edit)
- Challenge services
- Multi-flag support (CTFFlag model, add_flag, remove_flag, verify_flag)
"""

from __future__ import annotations

import pytest

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus
from ctf.models import CTFChallenge, CTFFlag
from ctf.services import (
    add_flag,
    create_challenge,
    delete_challenge,
    get_challenge,
    list_challenges_for_event,
    remove_flag,
    update_challenge,
    verify_flag,
)
from ctf.services.challenge import hash_flag

# =============================================================================
# Form Tests
# =============================================================================


class TestChallengeServices:
    """Tests for challenge service functions."""

    def test_create_challenge_success(self, ctf_event_draft):
        """create_challenge creates challenge with hashed flag."""
        challenge = create_challenge(
            event_id=ctf_event_draft.pk,
            challenge_data={
                "name": "Service Test Challenge",
                "description": "Created via service",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{service_test}",
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        assert challenge.pk is not None
        assert challenge.name == "Service Test Challenge"
        assert challenge.flag_hash != "FLAG{service_test}"
        assert len(challenge.flag_hash) > 0

    def test_create_challenge_rejects_active_event(self, ctf_event_active):
        """create_challenge rejects adding to non-modifiable event."""
        from ctf.exceptions import CTFStateError

        with pytest.raises(CTFStateError):
            create_challenge(
                event_id=ctf_event_active.pk,
                challenge_data={
                    "name": "Should Fail",
                    "description": "Desc",
                    "category": ChallengeCategory.WEB.value,
                    "points": 100,
                    "difficulty": ChallengeDifficulty.EASY.value,
                    "flag": "FLAG{test}",
                },
                actor_id=ctf_event_active.created_by_id,
            )

    def test_create_challenge_requires_flag(self, ctf_event_draft):
        """create_challenge requires flag in data."""
        from ctf.exceptions import CTFValidationError

        with pytest.raises(CTFValidationError):
            create_challenge(
                event_id=ctf_event_draft.pk,
                challenge_data={
                    "name": "No Flag",
                    "description": "Desc",
                    "category": ChallengeCategory.WEB.value,
                    "points": 100,
                    "difficulty": ChallengeDifficulty.EASY.value,
                    # No flag provided
                },
                actor_id=ctf_event_draft.created_by_id,
            )

    def test_update_challenge_success(self, ctf_challenge):
        """update_challenge updates challenge fields."""
        # Need a draft event for this challenge
        ctf_challenge.event.status = EventStatus.DRAFT.value
        ctf_challenge.event.save()

        updated = update_challenge(
            challenge_id=ctf_challenge.pk,
            challenge_data={
                "points": 250,
                "target_instance_name": "windows-target",
                "target_port": 3389,
            },
            actor_id=ctf_challenge.event.created_by_id,
        )
        assert updated.points == 250
        assert updated.target_instance_name == "windows-target"
        assert updated.target_port == 3389

    def test_update_challenge_rehashes_flag(self, ctf_challenge):
        """update_challenge rehashes flag when provided."""
        ctf_challenge.event.status = EventStatus.DRAFT.value
        ctf_challenge.event.save()

        old_hash = ctf_challenge.flag_hash
        updated = update_challenge(
            challenge_id=ctf_challenge.pk,
            challenge_data={"flag": "FLAG{new_flag}"},
            actor_id=ctf_challenge.event.created_by_id,
        )
        assert updated.flag_hash != old_hash

    def test_update_challenge_rejects_active_event(self, ctf_challenge):
        """update_challenge rejects updating in active event."""
        from ctf.exceptions import CTFStateError

        ctf_challenge.event.status = EventStatus.ACTIVE.value
        ctf_challenge.event.save()

        with pytest.raises(CTFStateError):
            update_challenge(
                challenge_id=ctf_challenge.pk,
                challenge_data={"points": 999},
                actor_id=ctf_challenge.event.created_by_id,
            )

    def test_delete_challenge_soft_deletes(self, ctf_event_draft):
        """delete_challenge performs soft delete."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="To Delete",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="hash",
        )
        challenge_id = challenge.pk

        delete_challenge(challenge_id, actor_id=ctf_event_draft.created_by_id)

        # Should be soft-deleted
        assert not CTFChallenge.objects.filter(pk=challenge_id).exists()
        assert CTFChallenge.all_objects.filter(pk=challenge_id).exists()

    def test_delete_challenge_rejects_active_event(self, ctf_challenge):
        """delete_challenge rejects deleting from active event."""
        from ctf.exceptions import CTFStateError

        ctf_challenge.event.status = EventStatus.ACTIVE.value
        ctf_challenge.event.save()

        with pytest.raises(CTFStateError):
            delete_challenge(ctf_challenge.pk, actor_id=ctf_challenge.event.created_by_id)

    def test_get_challenge_returns_challenge(self, ctf_challenge):
        """get_challenge returns the challenge."""
        result = get_challenge(ctf_challenge.pk)
        assert result.pk == ctf_challenge.pk
        assert result.name == ctf_challenge.name

    def test_get_challenge_raises_not_found(self, db):
        """get_challenge raises CTFNotFoundError for missing challenge."""
        from uuid import uuid4

        from ctf.exceptions import CTFNotFoundError

        with pytest.raises(CTFNotFoundError):
            get_challenge(uuid4())

    def test_list_challenges_for_event(self, ctf_event_draft):
        """list_challenges_for_event returns all event challenges."""
        CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Challenge A",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="hash1",
        )
        CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Challenge B",
            description="Desc",
            category=ChallengeCategory.CRYPTO.value,
            points=200,
            difficulty=ChallengeDifficulty.MEDIUM.value,
            flag_hash="hash2",
        )

        challenges = list_challenges_for_event(ctf_event_draft.pk, actor_id=ctf_event_draft.created_by_id)
        assert challenges.count() == 2


class TestChallengeServiceOwnership:
    """Direct service callers must be subject to the same ownership policy
    as the API/HTML view layer.

    Issue #765: a future caller that bypasses the views (an internal job, an
    administrative script, a new endpoint that forgets the `_check_event_ownership`
    helper) must not be able to mutate another organizer's event content.
    """

    def test_list_challenges_for_event_rejects_other_organizer(self, ctf_event_draft, second_organizer_user):
        from ctf.exceptions import CTFPermissionError

        with pytest.raises(CTFPermissionError):
            list_challenges_for_event(ctf_event_draft.pk, actor_id=second_organizer_user.pk)

    def test_create_challenge_rejects_other_organizer(self, ctf_event_draft, second_organizer_user):
        from ctf.exceptions import CTFPermissionError

        with pytest.raises(CTFPermissionError):
            create_challenge(
                event_id=ctf_event_draft.pk,
                challenge_data={
                    "name": "Should Be Refused",
                    "description": "Created by non-owner",
                    "category": ChallengeCategory.WEB.value,
                    "points": 100,
                    "difficulty": ChallengeDifficulty.EASY.value,
                    "flag": "FLAG{nope}",
                },
                actor_id=second_organizer_user.pk,
            )

    def test_update_challenge_rejects_other_organizer(self, ctf_challenge, second_organizer_user):
        from ctf.exceptions import CTFPermissionError

        ctf_challenge.event.status = EventStatus.DRAFT.value
        ctf_challenge.event.save()

        with pytest.raises(CTFPermissionError):
            update_challenge(
                challenge_id=ctf_challenge.pk,
                challenge_data={"points": 999},
                actor_id=second_organizer_user.pk,
            )

    def test_delete_challenge_rejects_other_organizer(self, ctf_event_draft, second_organizer_user):
        from ctf.exceptions import CTFPermissionError

        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Owned",
            description="x",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="hash",
        )

        with pytest.raises(CTFPermissionError):
            delete_challenge(challenge.pk, actor_id=second_organizer_user.pk)


class TestMultiFlagVerification:
    """Tests for multi-flag verification (CTFFlag model)."""

    def test_verify_flag_with_ctfflag_records(self, ctf_event_draft):
        """verify_flag checks CTFFlag records when they exist."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Multi-flag Challenge",
            description="Multiple valid flags",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="legacy_hash",
        )
        # Add two flags
        CTFFlag.objects.create(
            challenge=challenge,
            flag_hash=hash_flag("FLAG{alpha}"),
            flag_type="static",
            case_sensitive=True,
            order=0,
        )
        CTFFlag.objects.create(
            challenge=challenge,
            flag_hash=hash_flag("FLAG{beta}"),
            flag_type="static",
            case_sensitive=True,
            order=1,
        )

        # Either flag should be accepted
        assert verify_flag(challenge, "FLAG{alpha}") is True
        assert verify_flag(challenge, "FLAG{beta}") is True
        # Wrong flag should fail
        assert verify_flag(challenge, "FLAG{wrong}") is False

    def test_verify_flag_backward_compat_no_ctfflag(self, ctf_event_draft):
        """verify_flag falls back to challenge.flag_hash when no CTFFlag records."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Legacy Challenge",
            description="Uses legacy flag_hash",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash=hash_flag("FLAG{legacy}"),
        )
        # No CTFFlag records - should use challenge.flag_hash
        assert verify_flag(challenge, "FLAG{legacy}") is True
        assert verify_flag(challenge, "FLAG{wrong}") is False

    def test_verify_flag_static_case_insensitive(self, ctf_event_draft):
        """Static flag with case_sensitive=False normalizes to lowercase."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Case Insensitive",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        CTFFlag.objects.create(
            challenge=challenge,
            flag_hash=hash_flag("flag{myvalue}", case_sensitive=False),
            flag_type="static",
            case_sensitive=False,
            order=0,
        )

        assert verify_flag(challenge, "FLAG{MyValue}") is True
        assert verify_flag(challenge, "flag{myvalue}") is True
        assert verify_flag(challenge, "FLAG{MYVALUE}") is True
        assert verify_flag(challenge, "FLAG{wrong}") is False

    def test_verify_flag_regex_type(self, ctf_event_draft):
        """Regex flag type uses re.fullmatch."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Regex Challenge",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        CTFFlag.objects.create(
            challenge=challenge,
            flag_hash=r"FLAG\{[a-f0-9]{8}\}",
            flag_type="regex",
            case_sensitive=True,
            order=0,
        )

        assert verify_flag(challenge, "FLAG{deadbeef}") is True
        assert verify_flag(challenge, "FLAG{12345678}") is True
        assert verify_flag(challenge, "FLAG{DEADBEEF}") is False  # uppercase fails (case sensitive)
        assert verify_flag(challenge, "FLAG{short}") is False

    def test_verify_flag_regex_case_insensitive(self, ctf_event_draft):
        """Regex flag with case_sensitive=False uses re.IGNORECASE."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Regex Case Insensitive",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        CTFFlag.objects.create(
            challenge=challenge,
            flag_hash=r"FLAG\{[a-f0-9]{8}\}",
            flag_type="regex",
            case_sensitive=False,
            order=0,
        )

        assert verify_flag(challenge, "FLAG{deadbeef}") is True
        assert verify_flag(challenge, "FLAG{DEADBEEF}") is True
        assert verify_flag(challenge, "flag{deadbeef}") is True

    def test_verify_flag_any_match_sufficient(self, ctf_event_draft):
        """Any matching flag in a multi-flag challenge is a solve."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Mixed Flags",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        # Static flag
        CTFFlag.objects.create(
            challenge=challenge,
            flag_hash=hash_flag("FLAG{static_answer}"),
            flag_type="static",
            case_sensitive=True,
            order=0,
        )
        # Regex flag
        CTFFlag.objects.create(
            challenge=challenge,
            flag_hash=r"FLAG\{user_\d+\}",
            flag_type="regex",
            case_sensitive=True,
            order=1,
        )

        # Static match
        assert verify_flag(challenge, "FLAG{static_answer}") is True
        # Regex match
        assert verify_flag(challenge, "FLAG{user_42}") is True
        # Neither match
        assert verify_flag(challenge, "FLAG{wrong}") is False


class TestFlagServiceFunctions:
    """Tests for add_flag and remove_flag service functions."""

    def test_add_flag_static(self, ctf_event_draft):
        """add_flag creates a static flag with hashed value."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Add Flag Test",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        flag_obj = add_flag(challenge.pk, {"flag": "FLAG{added}"}, actor_id=challenge.event.created_by_id)

        assert flag_obj.pk is not None
        assert flag_obj.flag_type == "static"
        assert flag_obj.case_sensitive is True
        assert flag_obj.flag_hash != "FLAG{added}"  # should be hashed
        assert flag_obj.flag_hash.startswith(("$2", "pbkdf2:"))

    def test_add_flag_regex(self, ctf_event_draft):
        """add_flag creates a regex flag with plaintext pattern."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Regex Flag Test",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        flag_obj = add_flag(
            challenge.pk,
            {
                "flag": r"FLAG\{[a-z]+\}",
                "flag_type": "regex",
            },
            actor_id=challenge.event.created_by_id,
        )

        assert flag_obj.flag_type == "regex"
        assert flag_obj.flag_hash == r"FLAG\{[a-z]+\}"  # stored as plaintext

    def test_add_flag_case_insensitive(self, ctf_event_draft):
        """add_flag with case_sensitive=False normalizes hash."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Case Insensitive Flag Test",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        flag_obj = add_flag(
            challenge.pk,
            {
                "flag": "FLAG{TestValue}",
                "case_sensitive": False,
            },
            actor_id=challenge.event.created_by_id,
        )

        assert flag_obj.case_sensitive is False
        # Verify the hash works with lowercased input
        from ctf.services.challenge import verify_single_flag

        assert verify_single_flag(flag_obj, "flag{testvalue}") is True
        assert verify_single_flag(flag_obj, "FLAG{TESTVALUE}") is True

    def test_add_flag_rejects_invalid_regex(self, ctf_event_draft):
        """add_flag rejects invalid regex patterns."""
        from ctf.exceptions import CTFValidationError

        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Bad Regex Test",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        with pytest.raises(CTFValidationError):
            add_flag(
                challenge.pk,
                {
                    "flag": r"FLAG\{[invalid",  # unclosed bracket
                    "flag_type": "regex",
                },
                actor_id=challenge.event.created_by_id,
            )

    def test_add_flag_rejects_active_event(self, ctf_event_active):
        """add_flag rejects adding to non-modifiable event."""
        from ctf.exceptions import CTFStateError

        challenge = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Active Flag Test",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        with pytest.raises(CTFStateError):
            add_flag(challenge.pk, {"flag": "FLAG{test}"}, actor_id=challenge.event.created_by_id)

    def test_add_flag_requires_flag_value(self, ctf_event_draft):
        """add_flag requires non-empty flag value."""
        from ctf.exceptions import CTFValidationError

        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Empty Flag Test",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        with pytest.raises(CTFValidationError):
            add_flag(challenge.pk, {"flag": ""}, actor_id=challenge.event.created_by_id)

    def test_remove_flag(self, ctf_event_draft):
        """remove_flag soft-deletes a flag."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Remove Flag Test",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        flag_obj = add_flag(challenge.pk, {"flag": "FLAG{to_remove}"}, actor_id=challenge.event.created_by_id)
        flag_id = flag_obj.pk

        remove_flag(flag_id, actor_id=challenge.event.created_by_id)

        # Should be soft-deleted
        assert not CTFFlag.objects.filter(pk=flag_id).exists()
        assert CTFFlag.all_objects.filter(pk=flag_id).exists()

    def test_remove_flag_rejects_active_event(self, ctf_event_draft):
        """remove_flag rejects removing from non-modifiable event."""
        from ctf.exceptions import CTFStateError

        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Remove Active Flag Test",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="placeholder",
        )
        flag_obj = add_flag(challenge.pk, {"flag": "FLAG{test}"}, actor_id=challenge.event.created_by_id)

        # Change event to active
        ctf_event_draft.status = EventStatus.ACTIVE.value
        ctf_event_draft.save()

        with pytest.raises(CTFStateError):
            remove_flag(flag_obj.pk, actor_id=flag_obj.challenge.event.created_by_id)

    def test_remove_flag_not_found(self, db):
        """remove_flag raises CTFNotFoundError for missing flag."""
        from uuid import uuid4

        from ctf.exceptions import CTFNotFoundError

        with pytest.raises(CTFNotFoundError):
            remove_flag(uuid4(), actor_id=1)


class TestCreateChallengeWithFlags:
    """Tests for create_challenge with the 'flags' parameter."""

    def test_create_challenge_with_flags_list(self, ctf_event_draft):
        """create_challenge creates CTFFlag records from flags list."""
        challenge = create_challenge(
            event_id=ctf_event_draft.pk,
            challenge_data={
                "name": "Multi-flag Create",
                "description": "Created with multiple flags",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flags": [
                    {"flag": "FLAG{first}", "flag_type": "static"},
                    {"flag": r"FLAG\{user_\d+\}", "flag_type": "regex"},
                ],
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        assert challenge.pk is not None
        assert challenge.flags.count() == 2

        # Verify both flags work
        assert verify_flag(challenge, "FLAG{first}") is True
        assert verify_flag(challenge, "FLAG{user_99}") is True
        assert verify_flag(challenge, "FLAG{wrong}") is False

    def test_create_challenge_with_single_flag_still_works(self, ctf_event_draft):
        """create_challenge with single 'flag' param still works (backward compat)."""
        challenge = create_challenge(
            event_id=ctf_event_draft.pk,
            challenge_data={
                "name": "Single Flag Create",
                "description": "Created with single flag",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{single}",
            },
            actor_id=ctf_event_draft.created_by_id,
        )
        # No CTFFlag records created by create_challenge with single flag
        assert challenge.flags.count() == 0
        # But verify_flag still works via legacy fallback
        assert verify_flag(challenge, "FLAG{single}") is True
