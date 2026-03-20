"""Tests for CTF participant management views (admin views).

Tests cover:
- admin_participant_list: List participants with filtering
- admin_participant_import: CSV bulk import
- admin_participant_detail: Individual participant detail
- Participant APIs: CRUD operations
"""

from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from ctf.enums import ParticipantStatus
from ctf.models import CTFParticipant


class TestAdminParticipantListView:
    """Tests for the admin_participant_list view."""

    def test_lists_participants_for_event(self, authenticated_organizer_client, ctf_event):
        """View returns list of participants for the event."""
        # Create some participants
        CTFParticipant.objects.create(
            event=ctf_event,
            email="alice@test.com",
            name="Alice",
            status=ParticipantStatus.INVITED.value,
            invited_at=timezone.now(),
        )
        CTFParticipant.objects.create(
            event=ctf_event,
            email="bob@test.com",
            name="Bob",
            status=ParticipantStatus.REGISTERED.value,
            invited_at=timezone.now(),
            registered_at=timezone.now(),
        )

        url = reverse("ctf:admin_participant_list", kwargs={"event_id": ctf_event.id})
        response = authenticated_organizer_client.get(url)

        assert response.status_code == 200
        assert "Alice" in response.content.decode()
        assert "Bob" in response.content.decode()

    def test_filters_participants_by_status(self, authenticated_organizer_client, ctf_event):
        """View filters participants by status query parameter."""
        CTFParticipant.objects.create(
            event=ctf_event,
            email="invited@test.com",
            name="Invited User",
            status=ParticipantStatus.INVITED.value,
            invited_at=timezone.now(),
        )
        CTFParticipant.objects.create(
            event=ctf_event,
            email="registered@test.com",
            name="Registered User",
            status=ParticipantStatus.REGISTERED.value,
            registered_at=timezone.now(),
        )

        url = reverse("ctf:admin_participant_list", kwargs={"event_id": ctf_event.id})
        response = authenticated_organizer_client.get(url, {"status": "invited"})

        assert response.status_code == 200
        content = response.content.decode()
        assert "Invited User" in content
        # Registered user should not appear when filtering by invited
        assert "Registered User" not in content

    def test_shows_participant_stats(self, authenticated_organizer_client, ctf_event):
        """View shows participant statistics (total, invited, registered counts)."""
        CTFParticipant.objects.create(
            event=ctf_event,
            email="p1@test.com",
            name="P1",
            status=ParticipantStatus.INVITED.value,
            invited_at=timezone.now(),
        )
        CTFParticipant.objects.create(
            event=ctf_event,
            email="p2@test.com",
            name="P2",
            status=ParticipantStatus.INVITED.value,
            invited_at=timezone.now(),
        )
        CTFParticipant.objects.create(
            event=ctf_event,
            email="p3@test.com",
            name="P3",
            status=ParticipantStatus.REGISTERED.value,
            registered_at=timezone.now(),
        )

        url = reverse("ctf:admin_participant_list", kwargs={"event_id": ctf_event.id})
        response = authenticated_organizer_client.get(url)

        assert response.status_code == 200
        # Stats should be in context
        assert response.context["total_count"] == 3
        assert response.context["invited_count"] == 2
        assert response.context["registered_count"] == 1

    def test_denies_access_to_other_organizer_event(self, client, ctf_event, second_organizer_user):
        """View denies access to events owned by other organizers."""
        client.force_login(second_organizer_user)

        url = reverse("ctf:admin_participant_list", kwargs={"event_id": ctf_event.id})
        response = client.get(url)

        assert response.status_code == 403

    def test_returns_404_for_nonexistent_event(self, authenticated_organizer_client):
        """View returns 404 for non-existent event."""
        import uuid

        url = reverse(
            "ctf:admin_participant_list",
            kwargs={"event_id": uuid.uuid4()},
        )
        response = authenticated_organizer_client.get(url)

        assert response.status_code == 404

    def test_requires_login(self, client, ctf_event):
        """View requires authentication."""
        url = reverse("ctf:admin_participant_list", kwargs={"event_id": ctf_event.id})
        response = client.get(url)

        assert response.status_code == 302
        assert "login" in response.url

    def test_requires_organizer_role(self, authenticated_participant_client, ctf_event):
        """View requires organizer role, not participant."""
        url = reverse("ctf:admin_participant_list", kwargs={"event_id": ctf_event.id})
        response = authenticated_participant_client.get(url)

        assert response.status_code == 403


class TestAdminParticipantImportView:
    """Tests for the admin_participant_import view."""

    def test_get_shows_import_form(self, authenticated_organizer_client, ctf_event):
        """GET request shows the CSV import form."""
        url = reverse("ctf:admin_participant_import", kwargs={"event_id": ctf_event.id})
        response = authenticated_organizer_client.get(url)

        assert response.status_code == 200
        assert "form" in response.context

    def test_imports_participants_from_csv(self, authenticated_organizer_client, ctf_event):
        """POST with valid CSV creates participants."""
        url = reverse("ctf:admin_participant_import", kwargs={"event_id": ctf_event.id})

        csv_content = "Alice Smith,alice@example.com\nBob Jones,bob@example.com"

        from django.core.files.uploadedfile import SimpleUploadedFile

        csv_file = SimpleUploadedFile(
            "participants.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        response = authenticated_organizer_client.post(url, {"csv_file": csv_file})

        # Should redirect on success
        assert response.status_code == 302

        # Participants should be created
        assert CTFParticipant.objects.filter(event=ctf_event, email="alice@example.com").exists()
        assert CTFParticipant.objects.filter(event=ctf_event, email="bob@example.com").exists()

    def test_rejects_invalid_csv_format(self, authenticated_organizer_client, ctf_event):
        """POST with invalid CSV shows errors."""
        url = reverse("ctf:admin_participant_import", kwargs={"event_id": ctf_event.id})

        # Missing email column
        csv_content = "Just Name\nAnother Name"

        from django.core.files.uploadedfile import SimpleUploadedFile

        csv_file = SimpleUploadedFile(
            "participants.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        response = authenticated_organizer_client.post(url, {"csv_file": csv_file})

        # Should stay on page with errors
        assert response.status_code == 200
        assert "errors" in response.context or "error" in response.content.decode().lower()

    def test_rejects_duplicate_emails_in_csv(self, authenticated_organizer_client, ctf_event):
        """POST with duplicate emails in CSV shows error."""
        url = reverse("ctf:admin_participant_import", kwargs={"event_id": ctf_event.id})

        csv_content = "Alice,alice@example.com\nAlice Copy,alice@example.com"

        from django.core.files.uploadedfile import SimpleUploadedFile

        csv_file = SimpleUploadedFile(
            "participants.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        response = authenticated_organizer_client.post(url, {"csv_file": csv_file})

        assert response.status_code == 200
        # No participants should be created
        assert not CTFParticipant.objects.filter(event=ctf_event, email="alice@example.com").exists()

    def test_rejects_existing_participant_email(self, authenticated_organizer_client, ctf_event):
        """POST with email of existing participant shows error."""
        # Create existing participant
        CTFParticipant.objects.create(
            event=ctf_event,
            email="existing@example.com",
            name="Existing",
            status=ParticipantStatus.INVITED.value,
            invited_at=timezone.now(),
        )

        url = reverse("ctf:admin_participant_import", kwargs={"event_id": ctf_event.id})

        csv_content = "Existing User,existing@example.com\nNew User,new@example.com"

        from django.core.files.uploadedfile import SimpleUploadedFile

        csv_file = SimpleUploadedFile(
            "participants.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        response = authenticated_organizer_client.post(url, {"csv_file": csv_file})

        assert response.status_code == 200
        # New user should not be created either (atomic failure)
        assert not CTFParticipant.objects.filter(event=ctf_event, email="new@example.com").exists()

    def test_denies_access_to_other_organizer_event(self, client, ctf_event, second_organizer_user):
        """View denies access to events owned by other organizers."""
        client.force_login(second_organizer_user)

        url = reverse("ctf:admin_participant_import", kwargs={"event_id": ctf_event.id})
        response = client.get(url)

        assert response.status_code == 403


class TestAdminParticipantDetailView:
    """Tests for the admin_participant_detail view."""

    def test_shows_participant_details(self, authenticated_organizer_client, ctf_event, ctf_participant):
        """View shows participant profile and statistics."""
        url = reverse(
            "ctf:admin_participant_detail",
            kwargs={"participant_id": ctf_participant.id},
        )
        response = authenticated_organizer_client.get(url)

        assert response.status_code == 200
        assert ctf_participant.name in response.content.decode()
        assert ctf_participant.email in response.content.decode()

    def test_shows_participant_submission_history(
        self,
        authenticated_organizer_client,
        ctf_event,
        ctf_participant,
        ctf_challenge,
        ctf_submission_correct,
    ):
        """View shows participant's submission history."""
        url = reverse(
            "ctf:admin_participant_detail",
            kwargs={"participant_id": ctf_participant.id},
        )
        response = authenticated_organizer_client.get(url)

        assert response.status_code == 200
        # Should show submission info
        assert "submissions" in response.context
        assert len(response.context["submissions"]) == 1

    def test_shows_participant_score(
        self,
        authenticated_organizer_client,
        ctf_participant,
        ctf_challenge,
        ctf_submission_correct,
    ):
        """View shows participant's total score."""
        url = reverse(
            "ctf:admin_participant_detail",
            kwargs={"participant_id": ctf_participant.id},
        )
        response = authenticated_organizer_client.get(url)

        assert response.status_code == 200
        assert response.context["total_score"] == ctf_challenge.points

    def test_returns_404_for_nonexistent_participant(self, authenticated_organizer_client):
        """View returns 404 for non-existent participant."""
        import uuid

        url = reverse(
            "ctf:admin_participant_detail",
            kwargs={"participant_id": uuid.uuid4()},
        )
        response = authenticated_organizer_client.get(url)

        assert response.status_code == 404

    def test_denies_access_to_other_organizer_participant(self, client, ctf_participant, second_organizer_user):
        """View denies access to participants in other organizers' events."""
        client.force_login(second_organizer_user)

        url = reverse(
            "ctf:admin_participant_detail",
            kwargs={"participant_id": ctf_participant.id},
        )
        response = client.get(url)

        assert response.status_code == 403


class TestAdminParticipantAddView:
    """Tests for adding a single participant."""

    def test_get_shows_add_form(self, authenticated_organizer_client, ctf_event):
        """GET request shows the add participant form."""
        url = reverse("ctf:admin_participant_add", kwargs={"event_id": ctf_event.id})
        response = authenticated_organizer_client.get(url)

        assert response.status_code == 200
        assert "form" in response.context

    def test_post_creates_participant(self, authenticated_organizer_client, ctf_event):
        """POST with valid data creates a participant."""
        url = reverse("ctf:admin_participant_add", kwargs={"event_id": ctf_event.id})

        response = authenticated_organizer_client.post(
            url,
            {
                "name": "New Participant",
                "email": "new@example.com",
            },
        )

        # Should redirect on success
        assert response.status_code == 302

        # Participant should be created and auto-registered
        participant = CTFParticipant.objects.get(event=ctf_event, email="new@example.com")
        assert participant.name == "New Participant"
        assert participant.status == ParticipantStatus.REGISTERED.value
        assert participant.user is not None

    def test_rejects_duplicate_email(self, authenticated_organizer_client, ctf_event):
        """POST with duplicate email shows error."""
        # Create existing participant
        CTFParticipant.objects.create(
            event=ctf_event,
            email="existing@example.com",
            name="Existing",
            status=ParticipantStatus.INVITED.value,
            invited_at=timezone.now(),
        )

        url = reverse("ctf:admin_participant_add", kwargs={"event_id": ctf_event.id})

        response = authenticated_organizer_client.post(
            url,
            {
                "name": "Duplicate",
                "email": "existing@example.com",
            },
        )

        assert response.status_code == 200
        assert "error" in response.content.decode().lower() or response.context.get("form").errors


class TestAPIParticipantList:
    """Tests for the api_participant_list endpoint."""

    def test_get_returns_participants_json(self, authenticated_organizer_client, ctf_event):
        """GET returns JSON list of participants."""
        CTFParticipant.objects.create(
            event=ctf_event,
            email="test@example.com",
            name="Test User",
            status=ParticipantStatus.INVITED.value,
            invited_at=timezone.now(),
        )

        url = reverse("ctf:api_participant_list", kwargs={"event_id": ctf_event.id})
        response = authenticated_organizer_client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert "participants" in data
        assert len(data["participants"]) == 1
        assert data["participants"][0]["email"] == "test@example.com"

    def test_post_creates_participant(self, authenticated_organizer_client, ctf_event):
        """POST creates a new participant."""
        url = reverse("ctf:api_participant_list", kwargs={"event_id": ctf_event.id})

        import json

        response = authenticated_organizer_client.post(
            url,
            data=json.dumps({"name": "API User", "email": "api@example.com"}),
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "api@example.com"

        # Verify created in DB
        assert CTFParticipant.objects.filter(event=ctf_event, email="api@example.com").exists()


class TestAPIParticipantDetail:
    """Tests for the api_participant_detail endpoint."""

    def test_get_returns_participant_json(self, authenticated_organizer_client, ctf_participant):
        """GET returns participant details as JSON."""
        url = reverse(
            "ctf:api_participant_detail",
            kwargs={"participant_id": ctf_participant.id},
        )
        response = authenticated_organizer_client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(ctf_participant.id)
        assert data["email"] == ctf_participant.email

    def test_delete_soft_deletes_participant(self, authenticated_organizer_client, ctf_event):
        """DELETE soft-deletes the participant."""
        participant = CTFParticipant.objects.create(
            event=ctf_event,
            email="delete@example.com",
            name="To Delete",
            status=ParticipantStatus.INVITED.value,
            invited_at=timezone.now(),
        )

        url = reverse(
            "ctf:api_participant_detail",
            kwargs={"participant_id": participant.id},
        )
        response = authenticated_organizer_client.delete(url)

        assert response.status_code == 200

        # Should be soft-deleted (not in default queryset)
        assert not CTFParticipant.objects.filter(id=participant.id).exists()
        # But still exists with deleted_at set
        assert CTFParticipant.all_objects.filter(id=participant.id).exists()


class TestAPIParticipantImport:
    """Tests for the api_participant_import endpoint."""

    def test_imports_from_json_array(self, authenticated_organizer_client, ctf_event):
        """POST imports participants from JSON array."""
        url = reverse("ctf:api_participant_import", kwargs={"event_id": ctf_event.id})

        import json

        response = authenticated_organizer_client.post(
            url,
            data=json.dumps(
                {
                    "participants": [
                        {"name": "User One", "email": "one@example.com"},
                        {"name": "User Two", "email": "two@example.com"},
                    ]
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["imported"] == 2

        # Verify created
        assert CTFParticipant.objects.filter(event=ctf_event, email="one@example.com").exists()
        assert CTFParticipant.objects.filter(event=ctf_event, email="two@example.com").exists()


class TestAPIParticipantResendInvite:
    """Tests for resending participant invites."""

    def test_resend_regenerates_token(self, authenticated_organizer_client, ctf_event):
        """Resend invite generates new token and updates expiry."""
        participant = CTFParticipant.objects.create(
            event=ctf_event,
            email="resend@example.com",
            name="Resend User",
            status=ParticipantStatus.INVITED.value,
            invited_at=timezone.now() - timedelta(days=5),
        )
        old_token = participant.invite_token

        url = reverse(
            "ctf:api_participant_resend_invite",
            kwargs={"participant_id": participant.id},
        )
        response = authenticated_organizer_client.post(url)

        assert response.status_code == 200

        participant.refresh_from_db()
        assert participant.invite_token != old_token

    def test_resend_works_for_registered_participant(self, authenticated_organizer_client, ctf_participant):
        """Resend works for registered participants (sends magic link)."""
        # ctf_participant fixture has user linked (registered)
        url = reverse(
            "ctf:api_participant_resend_invite",
            kwargs={"participant_id": ctf_participant.id},
        )
        response = authenticated_organizer_client.post(url)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
