"""Validation and status projection for participant range recovery."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from ctf.enums import ParticipantStatus, RecoveryPhase, RecoveryStrategy
from ctf.exceptions import CTFNotFoundError, CTFRangeError, CTFValidationError
from ctf.models import CTFParticipant, CTFRangeRecovery
from ctf.services.range.recovery import get_recovery_status, recover_participant_range
from tests.ctf.test_services.test_range_recovery import event_with_scenario as event_with_scenario
from tests.ctf.test_services.test_range_recovery import rich_participant as rich_participant
from tests.ctf.test_services.test_range_recovery import team_and_bracket as team_and_bracket


class TestValidationAndFailures:
    @pytest.mark.django_db
    def test_participant_not_found(self, organizer_user):
        with pytest.raises(CTFNotFoundError):
            recover_participant_range(
                uuid4(),
                strategy=RecoveryStrategy.REBUILD.value,
                operator=organizer_user,
            )

    @pytest.mark.django_db
    def test_invalid_strategy(self, rich_participant, organizer_user):
        participant, _ = rich_participant
        with pytest.raises(CTFValidationError):
            recover_participant_range(
                participant.pk,
                strategy="not_a_real_strategy",
                operator=organizer_user,
            )
        assert not CTFRangeRecovery.objects.filter(participant=participant).exists()

    @pytest.mark.django_db
    def test_unregistered_participant_rejected(self, event_with_scenario, organizer_user):
        participant = CTFParticipant.objects.create(
            event=event_with_scenario,
            user=None,
            email="unregistered@test.com",
            name="Unregistered",
            status=ParticipantStatus.REGISTERED.value,
        )
        with pytest.raises(CTFValidationError, match="registered"):
            recover_participant_range(
                participant.pk,
                strategy=RecoveryStrategy.REBUILD.value,
                operator=organizer_user,
            )

    @pytest.mark.django_db
    def test_participant_with_no_range_rejected(self, event_with_scenario, participant_user, organizer_user):
        participant = CTFParticipant.objects.create(
            event=event_with_scenario,
            user=participant_user,
            email=participant_user.email,
            name="No Range Participant",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        with pytest.raises(CTFRangeError, match="no range"):
            recover_participant_range(
                participant.pk,
                strategy=RecoveryStrategy.REBUILD.value,
                operator=organizer_user,
            )


class TestGetRecoveryStatus:
    @pytest.mark.django_db
    def test_returns_none_when_no_recovery_exists(self, rich_participant):
        participant, _ = rich_participant
        assert get_recovery_status(participant.pk) is None

    @pytest.mark.django_db
    def test_returns_latest_recovery_after_completion(self, rich_participant, organizer_user):
        participant, _ = rich_participant

        recover_participant_range(
            participant.pk,
            strategy=RecoveryStrategy.REBUILD.value,
            operator=organizer_user,
        )

        status = get_recovery_status(participant.pk)
        assert status is not None
        assert status["phase"] == RecoveryPhase.COMPLETED.value
        assert status["strategy"] == RecoveryStrategy.REBUILD.value
        assert status["replacement_range_instance_id"] is not None
