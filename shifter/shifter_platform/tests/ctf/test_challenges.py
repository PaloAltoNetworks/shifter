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
from django.urls import reverse

from ctf.enums import ChallengeCategory, ChallengeDifficulty
from ctf.forms import CTFChallengeForm
from ctf.models import CTFChallenge

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

    def test_form_save_is_blocked(self, ctf_event_draft):
        """`CTFChallengeForm.save()` must raise — codex cycle 7 trap.

        ModelForm's default save() bypasses the service-layer actor check,
        field allowlist, flag hashing, multi-flag handling, tag/topic
        resolution, and release-task sync. The override raises so callers
        cannot silently regress to that path.
        """
        form = CTFChallengeForm(
            data={
                "name": "Should Not Save",
                "description": "x",
                "category": ChallengeCategory.WEB.value,
                "points": 100,
                "difficulty": ChallengeDifficulty.EASY.value,
                "flag": "FLAG{nope}",
                "max_attempts": 0,
                "order": 0,
            },
            event=ctf_event_draft,
        )
        assert form.is_valid(), form.errors
        with pytest.raises(NotImplementedError, match="create_challenge"):
            form.save()

    def test_form_to_service_data_includes_flag(self, ctf_event_draft):
        """Form's `to_service_data()` returns the dict the service expects.

        Codex review (#765 cycle 5) routed admin POSTs through
        `create_challenge`/`update_challenge` so all challenge writes
        share one actor-checked service contract. The form is now a
        pure validation/DTO layer; persistence (including flag hashing)
        is the service's job. This test pins the DTO shape so the wiring
        between form and service can't silently drift.
        """
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
                "tag_list": "XDR, Linux",
                "topic_list": "SQL Injection",
            },
            event=ctf_event_draft,
        )
        assert form.is_valid(), form.errors
        data = form.to_service_data()
        assert data["name"] == "Test Challenge"
        assert data["flag"] == "FLAG{test_flag}"  # plaintext — service hashes
        assert data["tags"] == ["XDR", "Linux"]
        assert data["topics"] == ["SQL Injection"]


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
