"""Explicit receipt-context contracts for programmable and installed-app validators."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from ctf.extensions import register_flag_validator
from ctf.models import CTFFlag
from ctf.services.challenge import verify_single_flag
from ctf.validators import register_validator
from shared.receipt_validation import (
    ReceiptKeyMode,
    ReceiptSubmissionContext,
    ReceiptValidationContext,
    VerifiedReceiptEvidence,
)

pytestmark = pytest.mark.django_db


def _trusted_context(challenge) -> ReceiptValidationContext:
    return ReceiptValidationContext(
        deployment_id="gcp-dev",
        profile_id="proof-profile",
        provider_contract="proof-v1",
        event_id=challenge.event_id,
        participant_id=uuid4(),
        challenge_id=challenge.pk,
        range_instance_id=42,
        materialization_id=uuid4(),
        assignment_epoch=uuid4(),
        registration_revision=uuid4(),
        provider_range_namespace=uuid4().hex,
        provider_participant_namespace=uuid4().hex,
        issuer_id="proof-issuer",
        key_mode=ReceiptKeyMode.REMOTE_SYMMETRIC,
        algorithm_id="hmac-sha256",
        key_id="range-key-v1",
        public_verification_key="",
        reset_generation=0,
        registered_objectives=("objective-one", "objective-two"),
        objective_id="objective-one",
    )


def _submission_context(context: ReceiptValidationContext) -> ReceiptSubmissionContext:
    return ReceiptSubmissionContext(
        event_id=context.event_id,
        participant_id=context.participant_id,
        challenge_id=context.challenge_id,
        range_instance_id=context.range_instance_id,
        owner_user_id=1,
    )


def _evidence(context: ReceiptValidationContext) -> VerifiedReceiptEvidence:
    return VerifiedReceiptEvidence(
        receipt_id="provider-receipt-one",
        issuer_id=context.issuer_id,
        expires_at=timezone.now() + timedelta(minutes=5),
        context=context,
    )


def test_programmable_validator_receives_full_context_only_after_explicit_opt_in(ctf_challenge, monkeypatch):
    from ctf.validators import _SERVER_CONTEXT_VALIDATORS, _VALIDATORS

    context = _trusted_context(ctf_challenge)
    received = []

    def verifier(submitted, params, trusted_context):
        received.append((submitted, params, trusted_context))
        return _evidence(trusted_context)

    register_validator("receipt-programmable", verifier, supports_server_context=True)
    monkeypatch.setattr(
        "ctf.services.challenge._flag_verify._resolve_registered_receipt_context",
        lambda server_context, selection: context,
    )
    flag_obj = CTFFlag.objects.create(
        challenge=ctf_challenge,
        flag_hash="programmable",
        flag_type="programmable",
        validator_config={
            "validator_name": "receipt-programmable",
            "params": {"mode": "strict"},
            "receipt": {"protocol": "receipt-v1", "profile_id": "proof-profile", "objective_id": "objective-one"},
        },
    )
    evidence = []
    sensitive_attempts = []
    try:
        assert verify_single_flag(
            flag_obj,
            "opaque-receipt",
            server_context=_submission_context(context),
            evidence_collector=evidence.append,
            sensitive_submission_collector=lambda: sensitive_attempts.append(True),
        )
    finally:
        _VALIDATORS.pop("receipt-programmable", None)
        _SERVER_CONTEXT_VALIDATORS.discard("receipt-programmable")

    assert received == [("opaque-receipt", {"mode": "strict"}, context)]
    assert len(evidence) == 1
    assert sensitive_attempts == [True]
    assert evidence[0].receipt_id == "provider-receipt-one"
    assert evidence[0].context == context


def test_context_capable_validator_must_return_exact_evidence_not_a_boolean(ctf_challenge, monkeypatch):
    from ctf.validators import _SERVER_CONTEXT_VALIDATORS, _VALIDATORS

    context = _trusted_context(ctf_challenge)
    register_validator("unsafe-context-bool", lambda submitted, params, trusted: True, supports_server_context=True)
    monkeypatch.setattr(
        "ctf.services.challenge._flag_verify._resolve_registered_receipt_context",
        lambda server_context, selection: context,
    )
    flag_obj = CTFFlag.objects.create(
        challenge=ctf_challenge,
        flag_hash="programmable",
        flag_type="programmable",
        validator_config={"validator_name": "unsafe-context-bool", "receipt": {}},
    )
    try:
        assert not verify_single_flag(flag_obj, "opaque-receipt", server_context=_submission_context(context))
    finally:
        _VALIDATORS.pop("unsafe-context-bool", None)
        _SERVER_CONTEXT_VALIDATORS.discard("unsafe-context-bool")


def test_installed_app_validator_receives_same_full_context_contract(ctf_challenge, monkeypatch):
    from ctf.extensions import _flag_validators, _server_context_flag_validators

    context = _trusted_context(ctf_challenge)
    received = []

    def verifier(flag_obj, submitted, trusted_context):
        received.append((flag_obj.pk, submitted, trusted_context))
        return _evidence(trusted_context)

    register_flag_validator("receiptproof", verifier, supports_server_context=True)
    monkeypatch.setattr(
        "ctf.services.challenge._flag_verify._resolve_registered_receipt_context",
        lambda server_context, selection: context,
    )
    flag_obj = CTFFlag.objects.create(
        challenge=ctf_challenge,
        flag_hash="receipt-context",
        flag_type="receiptproof",
        validator_config={"protocol": "receipt-v1", "profile_id": "proof-profile", "objective_id": "objective-one"},
    )
    evidence = []
    sensitive_attempts = []
    try:
        assert verify_single_flag(
            flag_obj,
            "opaque-receipt",
            server_context=_submission_context(context),
            evidence_collector=evidence.append,
            sensitive_submission_collector=lambda: sensitive_attempts.append(True),
        )
    finally:
        _flag_validators.pop("receiptproof", None)
        _server_context_flag_validators.discard("receiptproof")

    assert received == [(flag_obj.pk, "opaque-receipt", context)]
    assert len(evidence) == 1
    assert sensitive_attempts == [True]
    assert evidence[0].receipt_id == "provider-receipt-one"
    assert evidence[0].context == context
