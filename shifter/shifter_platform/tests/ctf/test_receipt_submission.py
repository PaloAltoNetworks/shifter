"""End-to-end CTF scoring tests for participant-bound signed receipts."""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus, ParticipantStatus
from ctf.exceptions import CTFValidationError
from ctf.models import CTFChallenge, CTFEvent, CTFFlag, CTFParticipant, CTFReceiptConsumption
from ctf.services import submit_flag
from ctf.validators import ReceiptVerifierProfile, register_receipt_profile
from engine.models import Range
from engine.models import Request as EngineRequest
from engine.services import register_receipt_verifier, revoke_receipt_verifier
from shared.enums import RangeSource, RequestType, ResourceStatus
from shared.receipt_validation import (
    ReceiptKeyMode,
    ReceiptRegistrationDemand,
    ReceiptValidationContext,
)
from tests.ctf.receipt_test_transport import receipt_wire

pytestmark = pytest.mark.django_db

_WORKSPACE_ID = 818
_PROFILE_ID = "keplerops-penr1"
_OBJECTIVE = "flag-agent-control"


@pytest.fixture
def receipt_profile(monkeypatch):
    from ctf.validators import _receipt_profiles

    monkeypatch.setattr(_receipt_profiles, "_PROFILES", {})
    profile = ReceiptVerifierProfile(
        profile_id=_PROFILE_ID,
        deployment_id="gcp-dev",
        provider_contract="penr1-v1",
        endpoint_url="https://proof.example.test/v1/receipts/flag-agent-control/verify",
        audience="https://proof.example.test",
        service_auth_secret_ref="projects/test/secrets/receipt-callback/versions/1",
        issuer_id="keplerops-proof",
        allowed_key_modes=(ReceiptKeyMode.REMOTE_SYMMETRIC,),
        allowed_algorithms=("hmac-sha256",),
        permitted_objectives=(_OBJECTIVE,),
    )
    register_receipt_profile(profile)
    return profile


def _event(organizer):
    return CTFEvent.objects.create(
        name=f"Receipt event {uuid4()}",
        created_by=organizer,
        workspace_id=99,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=4),
        scenario_id="receipt-test",
    )


def _challenge(event, *, name="Receipt challenge"):
    challenge = CTFChallenge.objects.create(
        event=event,
        name=name,
        description="Submit protected proof",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.HARD.value,
    )
    CTFFlag.objects.create(
        challenge=challenge,
        flag_hash="http",
        flag_type="http",
        validator_config={"protocol": "receipt-v1", "profile_id": _PROFILE_ID, "objective_id": _OBJECTIVE},
    )
    return challenge


def _participant_with_range(event, user):
    request_id = uuid4()
    cms_request = CmsRequest.objects.create(
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=user,
        workspace_id=_WORKSPACE_ID,
    )
    engine_request = EngineRequest.objects.create(
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=user,
    )
    engine_range = Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=engine_request,
        user=user,
        cms_user_id=user.pk,
        status=Range.Status.READY,
        provisioner_operation="provision",
        provisioner_operation_id=request_id,
    )
    instance = RangeInstance.objects.create(
        request=cms_request,
        scenario_id="receipt-test",
        user_id=user.pk,
        workspace_id=_WORKSPACE_ID,
        status=ResourceStatus.READY.value,
        range_source=RangeSource.CTF.value,
        expires_at=timezone.now() + timedelta(hours=4),
        maximum_expires_at=timezone.now() + timedelta(hours=4),
    )
    participant = CTFParticipant.objects.create(
        event=event,
        user=user,
        email=user.email,
        name=f"Participant {user.pk}",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
        range_instance_id=instance.pk,
        range_status=ResourceStatus.READY.value,
    )
    demand = ReceiptRegistrationDemand(
        deployment_id="gcp-dev",
        profile_id=_PROFILE_ID,
        provider_contract="penr1-v1",
        ctf_event_id=event.pk,
        ctf_participant_id=participant.pk,
        objectives=(_OBJECTIVE,),
        issuer_id="keplerops-proof",
        provider_range_namespace="range-355-a1",
        provider_participant_namespace="participant-01",
        key_mode=ReceiptKeyMode.REMOTE_SYMMETRIC,
        algorithm_id="hmac-sha256",
        key_id="range-key-v1",
        reset_generation=0,
        secret_version_ref="projects/test/secrets/receipt-signing/versions/1",
    )
    binding = register_receipt_verifier(request_id, request_id, demand)
    return participant, instance, engine_range, demand, binding


def _context(participant, instance, demand, binding, challenge):
    return ReceiptValidationContext(
        deployment_id=binding.deployment_id,
        profile_id=binding.profile_id,
        provider_contract=binding.provider_contract,
        event_id=participant.event_id,
        participant_id=participant.pk,
        challenge_id=challenge.pk,
        range_instance_id=instance.pk,
        materialization_id=binding.materialization_id,
        assignment_epoch=binding.assignment_epoch,
        registration_revision=binding.registration_revision,
        provider_range_namespace=binding.provider_range_namespace,
        provider_participant_namespace=binding.provider_participant_namespace,
        issuer_id=binding.issuer_id,
        key_mode=binding.key_mode,
        algorithm_id=binding.algorithm_id,
        key_id=binding.key_id,
        public_verification_key=binding.public_verification_key,
        reset_generation=binding.reset_generation,
        registered_objectives=binding.objectives,
        objective_id=_OBJECTIVE,
    )


def _valid_response(context, *, receipt_id="penr1:proof-1"):
    return json.dumps(
        {
            "valid": True,
            "receipt_id": receipt_id,
            "issuer": context.issuer_id,
            "expires_at": (timezone.now() + timedelta(minutes=5)).isoformat(),
            "binding": {
                "event": str(context.event_id),
                "participant": context.provider_participant_namespace,
                "challenge": str(context.challenge_id),
                "range_instance": context.provider_range_namespace,
                "materialization": str(context.materialization_id),
                "assignment_epoch": str(context.assignment_epoch),
                "registration_revision": str(context.registration_revision),
                "reset_generation": context.reset_generation,
                "objective": context.objective_id,
            },
        }
    ).encode()


def test_bound_receipt_scores_once_and_persists_non_secret_consumption(
    organizer_user, participant_user, receipt_profile
):
    event = _event(organizer_user)
    challenge = _challenge(event)
    participant, instance, _range, demand, binding = _participant_with_range(event, participant_user)
    context = _context(participant, instance, demand, binding, challenge)
    with receipt_wire(_valid_response(context)):
        submission = submit_flag(participant.pk, challenge.pk, "PENR1.token")

    assert submission.is_correct is True
    consumed = CTFReceiptConsumption.objects.get(submission=submission)
    assert consumed.registration_revision == binding.registration_revision
    assert consumed.assignment_epoch == binding.assignment_epoch
    assert submission.submitted_flag == "[signed receipt redacted]"
    assert "PENR1.token" not in str(consumed.__dict__)


def test_rejected_receipt_attempt_is_redacted_from_submission_history(
    organizer_user, participant_user, receipt_profile
):
    event = _event(organizer_user)
    challenge = _challenge(event)
    participant, _instance, _range, _demand, _binding = _participant_with_range(event, participant_user)

    with receipt_wire(b'{"valid":false}'):
        submission = submit_flag(participant.pk, challenge.pk, "PENR1.rejected-sensitive-token")

    assert submission.is_correct is False
    assert submission.submitted_flag == "[signed receipt redacted]"


def test_consumption_survives_soft_deleted_submission_and_rejects_alternate_encoding(
    organizer_user, participant_user, receipt_profile
):
    event = _event(organizer_user)
    challenge = _challenge(event)
    participant, instance, _range, demand, binding = _participant_with_range(event, participant_user)
    context = _context(participant, instance, demand, binding, challenge)
    with receipt_wire(_valid_response(context, receipt_id="penr1:one-shot")):
        first = submit_flag(participant.pk, challenge.pk, "PENR1.first")
    first.delete(soft=True)

    with (
        receipt_wire(_valid_response(context, receipt_id="penr1:one-shot")),
        pytest.raises(CTFValidationError, match="already been redeemed"),
    ):
        submit_flag(participant.pk, challenge.pk, "PENR1.alternate-encoding")

    assert CTFReceiptConsumption.objects.count() == 1


def test_same_provider_objective_cannot_authorize_two_challenges(organizer_user, participant_user, receipt_profile):
    event = _event(organizer_user)
    first_challenge = _challenge(event, name="First receipt challenge")
    _challenge(event, name="Second receipt challenge")
    participant, _instance, _range, _demand, _binding = _participant_with_range(event, participant_user)

    with receipt_wire() as wire:
        submission = submit_flag(participant.pk, first_challenge.pk, "PENR1.ambiguous")

    assert submission.is_correct is False
    assert submission.submitted_flag == "[signed receipt redacted]"
    wire.boto_client_factory.assert_not_called()
    wire.connect.assert_not_called()


def test_scoring_rollback_leaves_verified_receipt_retryable(organizer_user, participant_user, receipt_profile):
    event = _event(organizer_user)
    challenge = _challenge(event)
    participant, instance, _range, demand, binding = _participant_with_range(event, participant_user)
    context = _context(participant, instance, demand, binding, challenge)

    def submit_then_abort() -> None:
        with transaction.atomic():
            submit_flag(participant.pk, challenge.pk, "PENR1.first-attempt")
            raise RuntimeError("later transaction work failed")

    response = _valid_response(context, receipt_id="penr1:retry-after-rollback")
    with receipt_wire(response), pytest.raises(RuntimeError, match="later transaction work failed"):
        submit_then_abort()

    assert not CTFReceiptConsumption.objects.exists()
    assert not participant.submissions.exists()

    with receipt_wire(_valid_response(context, receipt_id="penr1:retry-after-rollback")):
        retried = submit_flag(participant.pk, challenge.pk, "PENR1.retry")

    assert retried.is_correct is True
    assert CTFReceiptConsumption.objects.filter(submission=retried).exists()


def test_revoked_generation_cannot_commit_a_previously_verified_receipt(
    organizer_user, participant_user, receipt_profile
):
    event = _event(organizer_user)
    challenge = _challenge(event)
    participant, instance, _range, demand, binding = _participant_with_range(event, participant_user)
    context = _context(participant, instance, demand, binding, challenge)

    def revoke_before_response():
        assert revoke_receipt_verifier(demand_request_id(instance)) is True

    with (
        receipt_wire(_valid_response(context), before_response=revoke_before_response),
        pytest.raises(CTFValidationError, match="no longer active"),
    ):
        submit_flag(participant.pk, challenge.pk, "PENR1.token")
    assert not CTFReceiptConsumption.objects.exists()


def demand_request_id(instance):
    """Return the request UUID without crossing from CTF production code into CMS ORM."""
    return instance.request.request_id


def test_foreign_participant_without_the_registered_range_fails_before_callback(
    organizer_user, participant_user, second_participant_user, receipt_profile
):
    event = _event(organizer_user)
    challenge = _challenge(event)
    _participant_with_range(event, participant_user)
    foreign = CTFParticipant.objects.create(
        event=event,
        user=second_participant_user,
        email=second_participant_user.email,
        name="Foreign participant",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )

    with receipt_wire() as wire:
        submission = submit_flag(foreign.pk, challenge.pk, "PENR1.stolen")

    assert submission.is_correct is False
    assert submission.submitted_flag == "[signed receipt redacted]"
    wire.boto_client_factory.assert_not_called()
    wire.connect.assert_not_called()
