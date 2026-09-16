"""Receipt-aware verification and persistence support for CTF submissions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction

from ctf.exceptions import CTFValidationError
from ctf.models import CTFChallenge, CTFParticipant, CTFReceiptConsumption, CTFSubmission
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from shared.receipt_validation import ReceiptSubmissionContext, VerifiedReceiptEvidence

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SubmissionDecision:
    """Immutable result of lock-free flag verification and scoring."""

    is_correct: bool
    points: int
    receipt_evidence: VerifiedReceiptEvidence | None
    sensitive_submission: bool


def verify_and_score(
    participant: CTFParticipant,
    challenge: CTFChallenge,
    submitted_flag: str,
    *,
    verifier: Callable[..., bool],
) -> SubmissionDecision:
    """Verify and score before taking the participant transaction lock."""
    from ctf.services.hint import get_total_hint_penalty
    from ctf.services.scoring import calculate_solve_points

    total_hint_penalty = get_total_hint_penalty(participant.id, challenge.id)
    evidence: list[VerifiedReceiptEvidence] = []
    sensitive_submission_attempted = False

    def mark_sensitive_submission() -> None:
        """Remember that persistence must redact this submitted value."""
        nonlocal sensitive_submission_attempted
        sensitive_submission_attempted = True

    is_correct = verifier(
        challenge,
        submitted_flag.strip(),
        server_context=_submission_context(participant, challenge),
        receipt_submission=submitted_flag,
        evidence_collector=evidence.append,
        sensitive_submission_collector=mark_sensitive_submission,
    )
    points = calculate_solve_points(participant.event, challenge, total_hint_penalty) if is_correct else 0
    _log_decision(participant, challenge, is_correct, points)
    return SubmissionDecision(
        is_correct=is_correct,
        points=points,
        receipt_evidence=evidence[0] if evidence else None,
        sensitive_submission=sensitive_submission_attempted,
    )


def _log_decision(
    participant: CTFParticipant,
    challenge: CTFChallenge,
    is_correct: bool,
    points: int,
) -> None:
    """Log a bounded verification result without exposing the submission."""
    if is_correct:
        logger.info(
            "Correct flag submitted: participant=%s, challenge=%s, points=%d",
            participant.id,
            safe_log_value(challenge.id),
            points,
        )
    else:
        logger.debug(
            "Incorrect flag submitted: participant=%s, challenge=%s",
            participant.id,
            safe_log_value(challenge.id),
        )


def _submission_context(
    participant: CTFParticipant,
    challenge: CTFChallenge,
) -> ReceiptSubmissionContext | None:
    """Build trusted CTF facts without requiring a range for legacy flags."""
    if participant.user_id is None:
        return None
    from shared.receipt_validation import ReceiptSubmissionContext

    return ReceiptSubmissionContext(
        event_id=participant.event_id,
        participant_id=participant.pk,
        challenge_id=challenge.pk,
        range_instance_id=participant.range_instance_id,
        owner_user_id=participant.user_id,
    )


def revalidate_receipt_for_commit(
    evidence: VerifiedReceiptEvidence,
    participant: CTFParticipant,
    challenge: CTFChallenge,
) -> None:
    """Reauthorize callback evidence under participant and challenge locks."""
    from django.utils import timezone

    from ctf.services.challenge._receipt_context import revalidate_receipt_context

    context = evidence.context
    binding_matches = (
        context.event_id,
        context.participant_id,
        context.challenge_id,
        context.range_instance_id,
    ) == (
        participant.event_id,
        participant.pk,
        challenge.pk,
        participant.range_instance_id,
    )
    if evidence.expires_at <= timezone.now() or not binding_matches:
        raise CTFValidationError("Receipt registration is no longer active")
    revalidate_receipt_context(context)


def consume_receipt(submission: CTFSubmission, evidence: VerifiedReceiptEvidence) -> None:
    """Persist issuer-scoped one-shot evidence in the scoring transaction."""
    context = evidence.context
    identity = sha256(f"{evidence.issuer_id}\0{evidence.receipt_id}".encode()).hexdigest()
    try:
        # The savepoint keeps a uniqueness collision translatable without
        # poisoning the outer scoring transaction before it rolls back.
        with transaction.atomic():
            CTFReceiptConsumption.objects.create(
                submission=submission,
                receipt_identity_digest=f"sha256:{identity}",
                issuer_id=evidence.issuer_id,
                registration_revision=context.registration_revision,
                materialization_id=context.materialization_id,
                assignment_epoch=context.assignment_epoch,
                valid_until=evidence.expires_at,
            )
    except IntegrityError as exc:
        raise CTFValidationError(
            "This receipt has already been redeemed",
            code="CTF_RECEIPT_REPLAY",
        ) from exc
