"""Tests for CTF participant service registration deadline enforcement (CTF-007)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ctf.exceptions import CTFValidationError
from ctf.services.participant import bulk_import_participants, invite_participant


class TestRegistrationDeadlineSemantics:
    """CTF-705: the deadline closes self-registration; organizer adds bypass it."""

    def test_invite_allowed_after_deadline(self, ctf_event):
        """Organizer manual adds work after the deadline (late stragglers)."""
        ctf_event.registration_deadline = timezone.now() - timedelta(hours=1)
        ctf_event.save(update_fields=["registration_deadline"])

        participant = invite_participant(ctf_event.pk, "late@test.com", "Late User")
        assert participant.email == "late@test.com"

    def test_invite_allows_before_deadline(self, ctf_event):
        """invite_participant succeeds before deadline."""
        # Deadline must be before event_start per model validation
        ctf_event.registration_deadline = timezone.now() + timedelta(hours=12)
        ctf_event.save(update_fields=["registration_deadline"])

        participant = invite_participant(ctf_event.pk, "early@test.com", "Early User")
        assert participant.email == "early@test.com"

    def test_effective_deadline_defaults_to_event_start(self, ctf_event):
        """CTF-705: an unset deadline reads as the event start for display."""
        assert ctf_event.registration_deadline is None
        assert ctf_event.effective_registration_deadline == ctf_event.event_start

        participant = invite_participant(ctf_event.pk, "anytime@test.com", "Anytime User")
        assert participant.email == "anytime@test.com"

    def test_bulk_import_allowed_after_deadline(self, ctf_event):
        """Organizer-driven import also bypasses the self-registration deadline."""
        ctf_event.registration_deadline = timezone.now() - timedelta(hours=1)
        ctf_event.save(update_fields=["registration_deadline"])

        csv_content = "Alice,alice@test.com\nBob,bob@test.com"
        result = bulk_import_participants(ctf_event.pk, csv_content)
        assert len(result["created"]) == 2

    def test_bulk_import_allows_before_deadline(self, ctf_event):
        """bulk_import_participants succeeds before deadline."""
        ctf_event.registration_deadline = timezone.now() + timedelta(hours=12)
        ctf_event.save(update_fields=["registration_deadline"])

        csv_content = "Alice,alice@test.com"
        result = bulk_import_participants(ctf_event.pk, csv_content)
        assert len(result["created"]) == 1
        assert result["errors"] == []


@pytest.mark.django_db
class TestMaxParticipantsCap:
    """#1145: invite/import enforce max_participants under the event row lock."""

    def test_invite_rejects_when_at_capacity(self, ctf_event):
        ctf_event.max_participants = 2
        ctf_event.registration_deadline = None
        ctf_event.save(update_fields=["max_participants", "registration_deadline"])

        invite_participant(ctf_event.pk, "a@test.com", "A")
        invite_participant(ctf_event.pk, "b@test.com", "B")
        with pytest.raises(CTFValidationError) as exc:
            invite_participant(ctf_event.pk, "c@test.com", "C")

        assert exc.value.code == "CTF_MAX_PARTICIPANTS_REACHED"
        assert ctf_event.participants.count() == 2

    def test_bulk_import_rejects_when_exceeding_capacity(self, ctf_event):
        ctf_event.max_participants = 2
        ctf_event.registration_deadline = None
        ctf_event.save(update_fields=["max_participants", "registration_deadline"])

        invite_participant(ctf_event.pk, "a@test.com", "A")
        with pytest.raises(CTFValidationError):
            bulk_import_participants(ctf_event.pk, "B,b@test.com\nC,c@test.com")

        # The over-cap import is rejected wholesale; only the single invite remains.
        assert ctf_event.participants.count() == 1
