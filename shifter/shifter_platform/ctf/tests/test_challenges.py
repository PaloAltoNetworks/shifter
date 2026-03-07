"""Tests for CTF challenge management.

Tests for:
- Challenge forms
- Challenge views (list, create, detail, edit)
- Challenge services
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus
from ctf.forms import CTFChallengeForm
from ctf.models import CTFChallenge, CTFEvent
from ctf.services import (
    create_challenge,
    delete_challenge,
    get_challenge,
    list_challenges_for_event,
    update_challenge,
)


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
            },
            instance=ctf_challenge,
            event=ctf_challenge.event,
        )
        assert form.is_valid(), form.errors

    def test_form_validates_hint_penalty_requires_hint(self, ctf_event_draft):
        """Form rejects hint_penalty without hint text."""
        form = CTFChallengeForm(
            data={
                "name": "Test Challenge",
                "description": "Find the flag",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{test}",
                "hint": "",  # No hint
                "hint_penalty": 25,  # But penalty set
            },
            event=ctf_event_draft,
        )
        assert not form.is_valid()
        assert "hint_penalty" in form.errors

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
                "release_time": (ctf_event_draft.event_start - timedelta(days=1)).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
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
            },
            event=ctf_event_draft,
        )
        assert form.is_valid()
        challenge = form.save()
        # Flag should be hashed
        assert challenge.flag_hash != "FLAG{test_flag}"
        assert len(challenge.flag_hash) == 64  # SHA256 hex


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
        assert "/login/" in response.url

    def test_challenge_list_requires_organizer(
        self, authenticated_standard_client, ctf_event_draft
    ):
        """Challenge list requires organizer role."""
        url = reverse("ctf:admin_challenge_list", kwargs={"event_id": ctf_event_draft.pk})
        response = authenticated_standard_client.get(url)
        assert response.status_code == 403

    def test_challenge_list_returns_200(
        self, authenticated_organizer_client, ctf_event_draft
    ):
        """Challenge list returns 200 for organizer."""
        url = reverse("ctf:admin_challenge_list", kwargs={"event_id": ctf_event_draft.pk})
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200

    def test_challenge_list_shows_challenges(
        self, authenticated_organizer_client, ctf_event_draft
    ):
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

    def test_challenge_list_denies_other_organizer(
        self, client, second_organizer_user, ctf_event_draft
    ):
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

    def test_challenge_create_get_returns_form(
        self, authenticated_organizer_client, ctf_event_draft
    ):
        """Challenge create GET returns form."""
        url = reverse("ctf:admin_challenge_create", kwargs={"event_id": ctf_event_draft.pk})
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert "form" in response.context

    def test_challenge_create_post_creates_challenge(
        self, authenticated_organizer_client, ctf_event_draft
    ):
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
        }
        response = authenticated_organizer_client.post(url, data)
        assert response.status_code == 302  # Redirect on success

        challenge = CTFChallenge.objects.get(name="New Challenge")
        assert challenge.event == ctf_event_draft
        assert challenge.points == 100

    def test_challenge_create_rejects_active_event(
        self, authenticated_organizer_client, ctf_event_active
    ):
        """Challenge create rejects adding to active event."""
        url = reverse("ctf:admin_challenge_create", kwargs={"event_id": ctf_event_active.pk})
        response = authenticated_organizer_client.get(url)
        # Should redirect back since event is not modifiable
        assert response.status_code == 302

    def test_challenge_create_denies_other_organizer(
        self, client, second_organizer_user, ctf_event_draft
    ):
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

    def test_challenge_detail_returns_200(
        self, authenticated_organizer_client, ctf_challenge
    ):
        """Challenge detail returns 200 for organizer."""
        url = reverse("ctf:admin_challenge_detail", kwargs={"challenge_id": ctf_challenge.pk})
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert ctf_challenge.name in response.content.decode()

    def test_challenge_detail_shows_stats(
        self, authenticated_organizer_client, ctf_challenge, ctf_submission_correct
    ):
        """Challenge detail shows solve count."""
        url = reverse("ctf:admin_challenge_detail", kwargs={"challenge_id": ctf_challenge.pk})
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        # Solve count should be shown
        assert "1" in response.content.decode()

    def test_challenge_detail_denies_other_organizer(
        self, client, second_organizer_user, ctf_challenge
    ):
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

    def test_challenge_edit_get_returns_form(
        self, authenticated_organizer_client, ctf_challenge
    ):
        """Challenge edit GET returns form with data."""
        url = reverse("ctf:admin_challenge_edit", kwargs={"challenge_id": ctf_challenge.pk})
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert "form" in response.context
        assert response.context["form"].instance == ctf_challenge

    def test_challenge_edit_post_updates_challenge(
        self, authenticated_organizer_client, ctf_challenge
    ):
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
        }
        response = authenticated_organizer_client.post(url, data)
        assert response.status_code == 302

        ctf_challenge.refresh_from_db()
        assert ctf_challenge.name == "Updated Challenge Name"
        assert ctf_challenge.points == 150

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

    def test_challenge_edit_denies_other_organizer(
        self, client, second_organizer_user, ctf_challenge
    ):
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
            challenge_data={"points": 250},
        )
        assert updated.points == 250

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
