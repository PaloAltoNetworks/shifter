"""CTF-owned assembly of trusted signed-receipt validation context."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING
from uuid import UUID

from ctf.exceptions import CTFValidationError
from shared.receipt_validation import ReceiptSubmissionContext, ReceiptValidationContext, VerifiedReceiptEvidence

_REGISTRATION_INACTIVE = "Receipt registration is no longer active"
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ctf.models import CTFFlag


def resolve_receipt_validation_context(
    submission: ReceiptSubmissionContext,
    *,
    profile_id: str,
    objective_id: str,
) -> ReceiptValidationContext:
    """Resolve and cross-check one exact CTF→CMS→Engine assignment binding."""
    from ctf.bridges import cms_project_ctf_receipt_binding
    from ctf.validators import get_receipt_profile

    profile = get_receipt_profile(profile_id)
    if profile is None or objective_id not in profile.permitted_objectives:
        raise CTFValidationError("Receipt verifier profile is unavailable")
    _assert_unambiguous_objective_binding(
        event_id=submission.event_id,
        challenge_id=submission.challenge_id,
        profile_id=profile_id,
        objective_id=objective_id,
        lock=False,
    )
    if submission.range_instance_id is None:
        raise CTFValidationError("Receipt range binding is unavailable")
    try:
        binding = cms_project_ctf_receipt_binding(
            submission.range_instance_id,
            owner_user_id=submission.owner_user_id,
            event_id=submission.event_id,
            participant_id=submission.participant_id,
            profile_id=profile_id,
            objective_id=objective_id,
        )
    except Exception as exc:
        raise CTFValidationError("Receipt range binding is unavailable") from exc
    if not (
        binding.deployment_id == profile.deployment_id
        and binding.provider_contract == profile.provider_contract
        and binding.issuer_id == profile.issuer_id
        and binding.key_mode in profile.allowed_key_modes
        and binding.algorithm_id in profile.allowed_algorithms
    ):
        raise CTFValidationError("Receipt verifier registration does not match its deployment profile")
    return ReceiptValidationContext(
        deployment_id=binding.deployment_id,
        profile_id=binding.profile_id,
        provider_contract=binding.provider_contract,
        event_id=submission.event_id,
        participant_id=submission.participant_id,
        challenge_id=submission.challenge_id,
        range_instance_id=submission.range_instance_id,
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
        objective_id=objective_id,
    )


def resolve_registered_receipt_context(
    server_context: ReceiptSubmissionContext | None,
    selection: object,
) -> ReceiptValidationContext | None:
    """Resolve a closed receipt selection for an explicitly capable callback."""
    from ctf.validators import normalize_http_validator_config

    receipt_context = None
    if server_context is not None:
        try:
            canonical = normalize_http_validator_config(selection, check_destination=False)
            if canonical.get("protocol") == "receipt-v1":
                receipt_context = resolve_receipt_validation_context(
                    server_context,
                    profile_id=canonical["profile_id"],
                    objective_id=canonical["objective_id"],
                )
        except Exception:
            logger.warning("Receipt context resolution failed closed")
    return receipt_context


def accept_registered_evidence(
    result: object,
    context: ReceiptValidationContext,
    evidence_collector: Callable[[VerifiedReceiptEvidence], None] | None,
) -> bool:
    """Accept only exact, unexpired evidence from a context-capable callback."""
    from django.utils import timezone

    if (
        not isinstance(result, VerifiedReceiptEvidence)
        or result.context != context
        or result.expires_at <= timezone.now()
    ):
        return False
    if evidence_collector is not None:
        evidence_collector(result)
    return True


def revalidate_receipt_context(context: ReceiptValidationContext) -> None:
    """Fail if the callback's exact registration is no longer authoritative."""
    from ctf.bridges import cms_confirm_ctf_receipt_binding
    from ctf.validators import get_receipt_profile

    owner_user_id = _participant_owner_id(context)
    profile = get_receipt_profile(context.profile_id)
    if profile is None or not (
        context.deployment_id == profile.deployment_id
        and context.provider_contract == profile.provider_contract
        and context.issuer_id == profile.issuer_id
        and context.key_mode in profile.allowed_key_modes
        and context.algorithm_id in profile.allowed_algorithms
        and context.objective_id in profile.permitted_objectives
    ):
        raise CTFValidationError(_REGISTRATION_INACTIVE)
    _assert_unambiguous_objective_binding(
        event_id=context.event_id,
        challenge_id=context.challenge_id,
        profile_id=context.profile_id,
        objective_id=context.objective_id,
        lock=True,
    )
    from shared.receipt_validation import ReceiptVerifierBinding

    expected = ReceiptVerifierBinding(
        registration_revision=context.registration_revision,
        materialization_id=context.materialization_id,
        assignment_epoch=context.assignment_epoch,
        deployment_id=context.deployment_id,
        profile_id=context.profile_id,
        provider_contract=context.provider_contract,
        ctf_event_id=context.event_id,
        ctf_participant_id=context.participant_id,
        objectives=context.registered_objectives,
        issuer_id=context.issuer_id,
        key_mode=context.key_mode,
        algorithm_id=context.algorithm_id,
        key_id=context.key_id,
        public_verification_key=context.public_verification_key,
        provider_range_namespace=context.provider_range_namespace,
        provider_participant_namespace=context.provider_participant_namespace,
        reset_generation=context.reset_generation,
    )
    try:
        cms_confirm_ctf_receipt_binding(
            context.range_instance_id,
            owner_user_id=owner_user_id,
            objective_id=context.objective_id,
            expected=expected,
        )
    except Exception as exc:
        raise CTFValidationError(_REGISTRATION_INACTIVE) from exc


def _participant_owner_id(context: ReceiptValidationContext) -> int:
    """Reload the locked CTF participant's server-owned user identity."""
    from ctf.models import CTFParticipant

    participant = CTFParticipant.objects.get(pk=context.participant_id)
    if participant.user_id is None:
        raise CTFValidationError(_REGISTRATION_INACTIVE)
    return participant.user_id


def _assert_unambiguous_objective_binding(
    *,
    event_id: UUID,
    challenge_id: UUID,
    profile_id: str,
    objective_id: str,
    lock: bool,
) -> None:
    """Require one provider objective to name exactly one active challenge.

    PENR1 signs its provider-owned objective (``flag_id``), not a Shifter
    challenge UUID.  An organizer must therefore never be able to attach the
    same profile/objective pair to two challenges in an event and turn one
    receipt into two challenge authorizations.  The check is repeated under
    row locks immediately before commit so a live flag repair cannot race a
    verified receipt into a newly ambiguous mapping.
    """
    from ctf.models import CTFFlag

    flags = CTFFlag.objects.filter(
        challenge__event_id=event_id,
        challenge__deleted_at__isnull=True,
    ).only("challenge_id", "flag_type", "validator_config")
    if lock:
        flags = flags.select_for_update()
    matching_challenges = _matching_receipt_challenges(flags, profile_id, objective_id)
    if matching_challenges != {challenge_id}:
        raise CTFValidationError("Receipt objective is not uniquely bound to this challenge")


def _receipt_selection(flag_type: str, validator_config: object) -> tuple[str, str] | None:
    """Return a context-capable flag's canonical profile/objective selection."""
    selection = None
    if isinstance(validator_config, dict):
        if flag_type == "http":
            selection = _canonical_receipt_selection(validator_config)
        elif flag_type == "programmable":
            selection = _programmable_receipt_selection(validator_config)
        else:
            selection = _extension_receipt_selection(flag_type, validator_config)
    return selection


def _matching_receipt_challenges(flags: Iterable[CTFFlag], profile_id: str, objective_id: str) -> set[UUID]:
    """Return challenges selecting one exact receipt profile and objective."""
    return {
        flag.challenge_id
        for flag in flags
        if _receipt_selection(flag.flag_type, flag.validator_config) == (profile_id, objective_id)
    }


def _programmable_receipt_selection(config: dict[str, object]) -> tuple[str, str] | None:
    """Return the receipt selection for one capable programmable validator."""
    from ctf.validators import get_validator, validator_supports_server_context

    validator_name = config.get("validator_name")
    if not isinstance(validator_name, str) or get_validator(validator_name) is None:
        return None
    if not validator_supports_server_context(validator_name):
        return None
    return _canonical_receipt_selection(config.get("receipt"))


def _extension_receipt_selection(flag_type: str, config: dict[str, object]) -> tuple[str, str] | None:
    """Return the selection for a context-capable installed flag validator."""
    from ctf.extensions import flag_validator_supports_server_context, get_flag_validator

    if get_flag_validator(flag_type) is None or not flag_validator_supports_server_context(flag_type):
        return None
    return _canonical_receipt_selection(config)


def _canonical_receipt_selection(selection: object) -> tuple[str, str] | None:
    """Validate one stored receipt-v1 selection without resolving its profile."""
    if not isinstance(selection, dict) or selection.get("protocol") != "receipt-v1":
        return None
    profile_id = selection.get("profile_id")
    objective_id = selection.get("objective_id")
    if not isinstance(profile_id, str) or not isinstance(objective_id, str):
        return None
    return profile_id, objective_id
