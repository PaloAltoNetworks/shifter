"""Tests for CTF challenge management.

Tests for:
- Challenge forms
- Challenge views (list, create, detail, edit)
- Challenge services
- Multi-flag support (CTFFlag model, add_flag, remove_flag, verify_flag)
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus
from ctf.forms import CTFChallengeForm
from ctf.models import CTFChallenge, CTFFlag, CTFSubmission
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


class TestCTFChallengeForm:
    """Tests for the CTFChallengeForm."""

    def test_form_valid_with_all_fields(self, ctf_event_draft):
        """Form validates with all valid fields."""
        form = CTFChallengeForm(
            data={
                "name": "Test Challenge",
                "description": "Find the flag",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{test_flag}",
                "flag_format": "FLAG{...}",
                "hint": "",
                "hint_penalty": 0,
                "max_attempts": 0,
                "release_time": "",
                "order": 0,
                "target_instance_name": "windows-target",
                "target_port": 3389,
            },
            event=ctf_event_draft,
        )
        assert form.is_valid(), form.errors

    def test_form_requires_flag_for_new_challenge(self, ctf_event_draft):
        """Form requires flag when creating new challenge."""
        form = CTFChallengeForm(
            data={
                "name": "Test Challenge",
                "description": "Find the flag",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "",  # Empty flag
            },
            event=ctf_event_draft,
        )
        assert not form.is_valid()
        assert "flag" in form.errors

    def test_form_flag_optional_for_existing_challenge(self, ctf_challenge):
        """Form allows empty flag when editing existing challenge."""
        form = CTFChallengeForm(
            data={
                "name": ctf_challenge.name,
                "description": ctf_challenge.description,
                "category": ctf_challenge.category,
                "points": ctf_challenge.points,
                "difficulty": ctf_challenge.difficulty,
                "flag": "",  # Empty flag on edit
                "max_attempts": 0,
                "order": 0,
            },
            instance=ctf_challenge,
            event=ctf_challenge.event,
        )
        assert form.is_valid(), form.errors

    def test_form_validates_release_time_within_event(self, ctf_event_draft):
        """Form rejects release_time outside event bounds."""
        # Release time before event start
        form = CTFChallengeForm(
            data={
                "name": "Test Challenge",
                "description": "Find the flag",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{test}",
                "release_time": (ctf_event_draft.event_start - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
            },
            event=ctf_event_draft,
        )
        assert not form.is_valid()
        assert "release_time" in form.errors

    def test_form_save_hashes_flag(self, ctf_event_draft):
        """Form hashes flag on save."""
        form = CTFChallengeForm(
            data={
                "name": "Test Challenge",
                "description": "Find the flag",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{test_flag}",
                "hint_penalty": 0,
                "max_attempts": 0,
                "order": 0,
            },
            event=ctf_event_draft,
        )
        assert form.is_valid(), form.errors
        challenge = form.save()
        # Flag should be hashed (bcrypt or pbkdf2, not plaintext)
        assert challenge.flag_hash != "FLAG{test_flag}"
        assert challenge.flag_hash.startswith(("$2", "pbkdf2:"))


# =============================================================================
# View Tests
# =============================================================================


class TestChallengeListView:
    """Tests for the challenge list view."""

    def test_challenge_list_requires_login(self, client, ctf_event_draft):
        """Challenge list requires authentication."""
        url = reverse("ctf:admin_challenge_list", kwargs={"event_id": ctf_event_draft.pk})
        response = client.get(url)
        assert response.status_code == 302
        assert "login" in response.url

    def test_challenge_list_requires_organizer(self, authenticated_standard_client, ctf_event_draft):
        """Challenge list requires organizer role."""
        url = reverse("ctf:admin_challenge_list", kwargs={"event_id": ctf_event_draft.pk})
        response = authenticated_standard_client.get(url)
        assert response.status_code == 403

    def test_challenge_list_returns_200(self, authenticated_organizer_client, ctf_event_draft):
        """Challenge list returns 200 for organizer."""
        url = reverse("ctf:admin_challenge_list", kwargs={"event_id": ctf_event_draft.pk})
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200

    def test_challenge_list_shows_challenges(self, authenticated_organizer_client, ctf_event_draft):
        """Challenge list shows event's challenges."""
        # Create some challenges
        CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Challenge 1",
            description="Desc 1",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="hash1",
        )
        CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Challenge 2",
            description="Desc 2",
            category=ChallengeCategory.CRYPTO.value,
            points=200,
            difficulty=ChallengeDifficulty.MEDIUM.value,
            flag_hash="hash2",
        )

        url = reverse("ctf:admin_challenge_list", kwargs={"event_id": ctf_event_draft.pk})
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert "Challenge 1" in response.content.decode()
        assert "Challenge 2" in response.content.decode()

    def test_challenge_list_denies_other_organizer(self, client, second_organizer_user, ctf_event_draft):
        """Challenge list denies access to other organizers."""
        client.force_login(second_organizer_user)
        url = reverse("ctf:admin_challenge_list", kwargs={"event_id": ctf_event_draft.pk})
        response = client.get(url)
        assert response.status_code == 403


class TestChallengeCreateView:
    """Tests for the challenge create view."""

    def test_challenge_create_requires_login(self, client, ctf_event_draft):
        """Challenge create requires authentication."""
        url = reverse("ctf:admin_challenge_create", kwargs={"event_id": ctf_event_draft.pk})
        response = client.get(url)
        assert response.status_code == 302

    def test_challenge_create_get_returns_form(self, authenticated_organizer_client, ctf_event_draft):
        """Challenge create GET returns form."""
        url = reverse("ctf:admin_challenge_create", kwargs={"event_id": ctf_event_draft.pk})
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert "form" in response.context
        assert 'name="target_instance_name"' in response.content.decode()
        assert 'name="target_port"' in response.content.decode()

    def test_challenge_create_post_creates_challenge(self, authenticated_organizer_client, ctf_event_draft):
        """Challenge create POST creates new challenge."""
        url = reverse("ctf:admin_challenge_create", kwargs={"event_id": ctf_event_draft.pk})
        data = {
            "name": "New Challenge",
            "description": "Find the flag",
            "category": ChallengeCategory.WEB.value,
            "points": 100,
            "difficulty": ChallengeDifficulty.EASY.value,
            "flag": "FLAG{new_flag}",
            "flag_format": "FLAG{...}",
            "hint": "",
            "hint_penalty": 0,
            "max_attempts": 0,
            "order": 0,
            "target_instance_name": "windows-target",
            "target_port": 3389,
        }
        response = authenticated_organizer_client.post(url, data)
        assert response.status_code == 302  # Redirect on success

        challenge = CTFChallenge.objects.get(name="New Challenge")
        assert challenge.event == ctf_event_draft
        assert challenge.points == 100
        assert challenge.target_instance_name == "windows-target"
        assert challenge.target_port == 3389

    def test_challenge_create_rejects_active_event(self, authenticated_organizer_client, ctf_event_active):
        """Challenge create rejects adding to active event."""
        url = reverse("ctf:admin_challenge_create", kwargs={"event_id": ctf_event_active.pk})
        response = authenticated_organizer_client.get(url)
        # Should redirect back since event is not modifiable
        assert response.status_code == 302

    def test_challenge_create_denies_other_organizer(self, client, second_organizer_user, ctf_event_draft):
        """Challenge create denies access to other organizers."""
        client.force_login(second_organizer_user)
        url = reverse("ctf:admin_challenge_create", kwargs={"event_id": ctf_event_draft.pk})
        response = client.get(url)
        assert response.status_code == 403


class TestChallengeDetailView:
    """Tests for the challenge detail view."""

    def test_challenge_detail_requires_login(self, client, ctf_challenge):
        """Challenge detail requires authentication."""
        url = reverse("ctf:admin_challenge_detail", kwargs={"challenge_id": ctf_challenge.pk})
        response = client.get(url)
        assert response.status_code == 302

    def test_challenge_detail_returns_200(self, authenticated_organizer_client, ctf_challenge):
        """Challenge detail returns 200 for organizer."""
        url = reverse("ctf:admin_challenge_detail", kwargs={"challenge_id": ctf_challenge.pk})
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert ctf_challenge.name in response.content.decode()

    def test_challenge_detail_shows_stats(self, authenticated_organizer_client, ctf_challenge, ctf_submission_correct):
        """Challenge detail shows solve count."""
        url = reverse("ctf:admin_challenge_detail", kwargs={"challenge_id": ctf_challenge.pk})
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        # Solve count should be shown
        assert "1" in response.content.decode()

    def test_challenge_detail_denies_other_organizer(self, client, second_organizer_user, ctf_challenge):
        """Challenge detail denies access to other organizers."""
        client.force_login(second_organizer_user)
        url = reverse("ctf:admin_challenge_detail", kwargs={"challenge_id": ctf_challenge.pk})
        response = client.get(url)
        assert response.status_code == 403


class TestChallengeEditView:
    """Tests for the challenge edit view."""

    def test_challenge_edit_requires_login(self, client, ctf_challenge):
        """Challenge edit requires authentication."""
        url = reverse("ctf:admin_challenge_edit", kwargs={"challenge_id": ctf_challenge.pk})
        response = client.get(url)
        assert response.status_code == 302

    def test_challenge_edit_get_returns_form(self, authenticated_organizer_client, ctf_challenge):
        """Challenge edit GET returns form with data."""
        url = reverse("ctf:admin_challenge_edit", kwargs={"challenge_id": ctf_challenge.pk})
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert "form" in response.context
        assert response.context["form"].instance == ctf_challenge
        assert 'name="target_instance_name"' in response.content.decode()
        assert 'name="target_port"' in response.content.decode()

    def test_challenge_edit_post_updates_challenge(self, authenticated_organizer_client, ctf_challenge):
        """Challenge edit POST updates challenge."""
        url = reverse("ctf:admin_challenge_edit", kwargs={"challenge_id": ctf_challenge.pk})
        data = {
            "name": "Updated Challenge Name",
            "description": ctf_challenge.description,
            "category": ctf_challenge.category,
            "points": 150,
            "difficulty": ctf_challenge.difficulty,
            "flag": "",  # Keep existing flag
            "flag_format": ctf_challenge.flag_format,
            "hint": "",
            "hint_penalty": 0,
            "max_attempts": 0,
            "order": 0,
            "target_instance_name": "linux-web",
            "target_port": 8080,
        }
        response = authenticated_organizer_client.post(url, data)
        assert response.status_code == 302

        ctf_challenge.refresh_from_db()
        assert ctf_challenge.name == "Updated Challenge Name"
        assert ctf_challenge.points == 150
        assert ctf_challenge.target_instance_name == "linux-web"
        assert ctf_challenge.target_port == 8080

    def test_challenge_edit_rejects_non_modifiable_event(
        self, authenticated_organizer_client, ctf_event_active, organizer_user
    ):
        """Challenge edit rejects editing challenge in active event."""
        challenge = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Active Challenge",
            description="Desc",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="hash",
        )
        url = reverse("ctf:admin_challenge_edit", kwargs={"challenge_id": challenge.pk})
        response = authenticated_organizer_client.get(url)
        # Should redirect since event is not modifiable
        assert response.status_code == 302

    def test_challenge_edit_denies_other_organizer(self, client, second_organizer_user, ctf_challenge):
        """Challenge edit denies access to other organizers."""
        client.force_login(second_organizer_user)
        url = reverse("ctf:admin_challenge_edit", kwargs={"challenge_id": ctf_challenge.pk})
        response = client.get(url)
        assert response.status_code == 403


# =============================================================================
# Service Tests
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

        delete_challenge(challenge_id)

        # Should be soft-deleted
        assert not CTFChallenge.objects.filter(pk=challenge_id).exists()
        assert CTFChallenge.all_objects.filter(pk=challenge_id).exists()

    def test_delete_challenge_rejects_active_event(self, ctf_challenge):
        """delete_challenge rejects deleting from active event."""
        from ctf.exceptions import CTFStateError

        ctf_challenge.event.status = EventStatus.ACTIVE.value
        ctf_challenge.event.save()

        with pytest.raises(CTFStateError):
            delete_challenge(ctf_challenge.pk)

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

        challenges = list_challenges_for_event(ctf_event_draft.pk)
        assert challenges.count() == 2


# =============================================================================
# Multi-Flag Tests
# =============================================================================


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
        flag_obj = add_flag(challenge.pk, {"flag": "FLAG{added}"})

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
            add_flag(challenge.pk, {"flag": "FLAG{test}"})

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
            add_flag(challenge.pk, {"flag": ""})

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
        flag_obj = add_flag(challenge.pk, {"flag": "FLAG{to_remove}"})
        flag_id = flag_obj.pk

        remove_flag(flag_id)

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
        flag_obj = add_flag(challenge.pk, {"flag": "FLAG{test}"})

        # Change event to active
        ctf_event_draft.status = EventStatus.ACTIVE.value
        ctf_event_draft.save()

        with pytest.raises(CTFStateError):
            remove_flag(flag_obj.pk)

    def test_remove_flag_not_found(self, db):
        """remove_flag raises CTFNotFoundError for missing flag."""
        from uuid import uuid4

        from ctf.exceptions import CTFNotFoundError

        with pytest.raises(CTFNotFoundError):
            remove_flag(uuid4())


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
        )
        # No CTFFlag records created by create_challenge with single flag
        assert challenge.flags.count() == 0
        # But verify_flag still works via legacy fallback
        assert verify_flag(challenge, "FLAG{single}") is True


# =============================================================================
# Visibility control
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


# =============================================================================
# Challenge Tag Tests (CTF-113)
# =============================================================================


@pytest.mark.django_db
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
        )
        updated = update_challenge(challenge.id, {"tags": ["XDR"]})
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
        )
        assert challenge.tags.count() == 2
        updated = update_challenge(challenge.id, {"tags": []})
        assert updated.tags.count() == 0


# =============================================================================
# Challenge Solution Tests (CTF-117)
# =============================================================================


@pytest.mark.django_db
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
        )
        updated = update_challenge(challenge.id, {"solution": "Updated solution with ```code blocks```."})
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
        )
        ctf_event_draft.status = "ended"
        assert not bool(challenge.solution and ctf_event_draft.status in ("ended", "archived"))


# =============================================================================
# Challenge Topic Tests (CTF-119)
# =============================================================================


@pytest.mark.django_db
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
        )
        updated = update_challenge(challenge.id, {"topics": ["Privilege Escalation"]})
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
        )
        assert challenge.topics.count() == 2
        updated = update_challenge(challenge.id, {"topics": []})
        assert updated.topics.count() == 0


# =============================================================================
# Challenge Rating Tests (CTF-120)
# =============================================================================


@pytest.mark.django_db
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
        from ctf.models import CTFChallenge, CTFSubmission

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
        from ctf.models import CTFParticipant, CTFSubmission
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
        from ctf.models import CTFChallenge, CTFEvent, CTFParticipant, CTFSubmission
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


# =============================================================================
# Next Challenge Navigation Tests (CTF-121)
# =============================================================================


@pytest.mark.django_db
class TestNextChallengeNavigation:
    """Tests for next challenge navigation (CTF-121)."""

    def test_form_queryset_excludes_self(self, ctf_event_draft):
        """Form next_challenge queryset excludes the challenge being edited."""
        c1 = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="C1",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h1",
        )
        CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="C2",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h2",
        )
        form = CTFChallengeForm(instance=c1, event=ctf_event_draft)
        qs = form.fields["next_challenge"].queryset
        assert c1 not in qs
        assert qs.count() == 1

    def test_form_queryset_filters_by_event(self, ctf_event_draft, organizer_user):
        """Form next_challenge queryset only includes same-event challenges."""
        from ctf.models import CTFEvent

        other_event = CTFEvent.objects.create(
            name="Other Event",
            created_by=organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=ctf_event_draft.event_start,
            event_end=ctf_event_draft.event_end,
            scenario_id="basic",
        )
        CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Same Event",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h1",
        )
        CTFChallenge.objects.create(
            event=other_event,
            name="Other Event Challenge",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h2",
        )
        form = CTFChallengeForm(event=ctf_event_draft)
        qs = form.fields["next_challenge"].queryset
        assert qs.count() == 1
        assert qs.first().name == "Same Event"

    def test_next_challenge_link_shown_when_solved(
        self,
        client,
        ctf_event_active,
        participant_user,
    ):
        """Solved challenge with next_challenge shows navigation link."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        c1 = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Challenge 1",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h1",
        )
        c2 = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Challenge 2",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h2",
        )
        c1.next_challenge = c2
        c1.save()

        p = CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=ctf_event_active.event_start,
        )
        CTFSubmission.objects.create(
            participant=p,
            challenge=c1,
            submitted_flag="FLAG{x}",
            is_correct=True,
            points_awarded=100,
            attempt_number=1,
        )

        client.force_login(participant_user)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": c1.pk})
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        assert "Challenge 2" in content
        assert str(c2.pk) in content

    def test_next_challenge_link_hidden_when_not_configured(
        self,
        client,
        ctf_event_active,
        participant_user,
    ):
        """Solved challenge without next_challenge does not show link."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        c1 = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Solo Challenge",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h1",
        )
        p = CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=ctf_event_active.event_start,
        )
        CTFSubmission.objects.create(
            participant=p,
            challenge=c1,
            submitted_flag="FLAG{x}",
            is_correct=True,
            points_awarded=100,
            attempt_number=1,
        )

        client.force_login(participant_user)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": c1.pk})
        response = client.get(url)
        assert response.status_code == 200
        assert "Next:" not in response.content.decode()

    def test_challenge_detail_shows_connection_info_for_matching_target(
        self,
        client,
        ctf_event_active,
        participant_user,
    ):
        """Participant challenge detail shows resolved host and port for configured targets."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        challenge = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="RDP Challenge",
            description="Find the target",
            category=ChallengeCategory.NETWORK.value,
            points=200,
            difficulty=ChallengeDifficulty.MEDIUM.value,
            flag_hash="$2b$12$h3",
            target_instance_name="windows-target",
            target_port=3389,
        )
        CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=ctf_event_active.event_start,
            range_instance_id=42,
            range_status="ready",
        )

        client.force_login(participant_user)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": challenge.pk})
        with patch(
            "cms.services.get_range_target_instances",
            return_value=[
                {"name": "windows-target", "private_ip": "10.0.1.10", "os_type": "windows"},
            ],
        ):
            response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        assert "10.0.1.10:3389" in content
        assert "(windows-target)" in content

    def test_challenge_detail_hides_connection_info_when_target_missing(
        self,
        client,
        ctf_event_active,
        participant_user,
    ):
        """Participant challenge detail omits connection info when no target instance matches."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        challenge = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Missing Target",
            description="Find the target",
            category=ChallengeCategory.NETWORK.value,
            points=200,
            difficulty=ChallengeDifficulty.MEDIUM.value,
            flag_hash="$2b$12$h4",
            target_instance_name="windows-target",
            target_port=3389,
        )
        CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=ctf_event_active.event_start,
            range_instance_id=42,
            range_status="ready",
        )

        client.force_login(participant_user)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": challenge.pk})
        with patch("cms.services.get_range_target_instances", return_value=[]):
            response = client.get(url)

        assert response.status_code == 200
        assert "10.0.1.10" not in response.content.decode()


# =============================================================================
# Organizer Dashboard Tests (CTF-1301)
# =============================================================================


@pytest.mark.django_db
class TestOrganizerDashboard:
    """Tests for the enhanced organizer dashboard (CTF-1301)."""

    def test_dashboard_context_with_active_event(
        self,
        authenticated_organizer_client,
        ctf_event_active,
    ):
        """Dashboard includes active_events_data when active events exist."""
        url = reverse("ctf:admin_dashboard")
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert "active_events_data" in response.context
        assert len(response.context["active_events_data"]) == 1
        item = response.context["active_events_data"][0]
        assert item["event"].pk == ctf_event_active.pk
        assert "stats" in item
        assert "status_form" in item
        assert "range_ready" in item

    def test_dashboard_range_overview(
        self,
        authenticated_organizer_client,
        ctf_event_active,
    ):
        """Dashboard context includes range provisioning counts."""
        url = reverse("ctf:admin_dashboard")
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert "range_ready" in response.context
        assert "range_provisioning" in response.context
        assert "range_error" in response.context

    def test_dashboard_activity_feed_with_submissions(
        self,
        authenticated_organizer_client,
        ctf_event_active,
        participant_user,
    ):
        """Dashboard shows recent submissions in activity feed."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        challenge = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Dashboard Test",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h1",
        )
        p = CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=ctf_event_active.event_start,
        )
        CTFSubmission.objects.create(
            participant=p,
            challenge=challenge,
            submitted_flag="FLAG{x}",
            is_correct=True,
            points_awarded=100,
            attempt_number=1,
        )

        url = reverse("ctf:admin_dashboard")
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert len(response.context["recent_activity"]) == 1
        assert response.context["recent_activity"][0].is_correct is True

    def test_dashboard_no_active_events(
        self,
        authenticated_organizer_client,
        ctf_event_draft,
    ):
        """Dashboard works with no active events (empty sections)."""
        url = reverse("ctf:admin_dashboard")
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert response.context["active_events_data"] == []
        assert response.context["recent_activity"] == []

    def test_dashboard_quick_controls_post_pauses_event(
        self,
        authenticated_organizer_client,
        ctf_event_active,
    ):
        """Quick controls form POST to event detail pauses the active event."""
        url = reverse("ctf:admin_event_detail", kwargs={"event_id": ctf_event_active.pk})
        response = authenticated_organizer_client.post(url, {"action": "pause"})
        assert response.status_code == 302
        ctf_event_active.refresh_from_db()
        assert ctf_event_active.status == "paused"
