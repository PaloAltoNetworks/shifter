"""Engine-owned lifecycle for participant-bound receipt verifier registrations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, overload

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from shared.receipt_validation import (
    ReceiptKeyMode,
    ReceiptRegistrationDemand,
    ReceiptVerifierBinding,
)

from ._common import EngineError

if TYPE_CHECKING:
    from uuid import UUID

    from engine.models import Range, ReceiptVerifierRegistration

__all__ = [
    "ReceiptBindingUnavailable",
    "ReceiptRegistrationConflict",
    "confirm_receipt_verifier_binding",
    "project_receipt_verifier_binding",
    "register_receipt_verifier",
    "revoke_receipt_verifier",
]


class ReceiptRegistrationError(EngineError):
    """Base error for invalid or unavailable receipt registration operations."""


class ReceiptRegistrationConflict(ReceiptRegistrationError):
    """A range already has a different active receipt verifier binding."""


class ReceiptBindingUnavailable(ReceiptRegistrationError):
    """No exact, active, usable receipt verifier binding matches the request."""


@transaction.atomic
def register_receipt_verifier(
    request_id: UUID,
    provisioning_operation_id: UUID,
    demand: ReceiptRegistrationDemand,
) -> ReceiptVerifierBinding:
    """Register one exact verifier binding for a realized range assignment.

    An exact retry returns the original registration revision and assignment
    epoch.  A changed demand cannot overwrite an active registration; callers
    must explicitly revoke or advance the range lifecycle first.
    """
    from engine.models import Range, ReceiptVerifierRegistration

    if not isinstance(demand, ReceiptRegistrationDemand):
        raise ReceiptRegistrationError("receipt registration demand is invalid")
    range_obj = _locked_range(request_id)
    if range_obj.status not in {Range.Status.PROVISIONING, Range.Status.READY}:
        raise ReceiptBindingUnavailable("range is not in a registerable state")
    if (
        range_obj.provisioner_operation not in {"provision", "activate"}
        or range_obj.provisioner_operation_id is None
        or range_obj.provisioner_operation_id != provisioning_operation_id
    ):
        raise ReceiptBindingUnavailable("receipt registration operation generation is no longer current")

    active = ReceiptVerifierRegistration.objects.filter(
        range=range_obj,
        status=ReceiptVerifierRegistration.Status.ACTIVE,
    ).first()
    if active is not None:
        if _registration_matches(active, range_obj, demand):
            return _to_binding(active)
        raise ReceiptRegistrationConflict("range already has a different active receipt verifier registration")

    registration = ReceiptVerifierRegistration(
        range=range_obj,
        materialization_id=range_obj.uuid,
        provisioning_operation_id=provisioning_operation_id,
        deployment_id=demand.deployment_id,
        profile_id=demand.profile_id,
        provider_contract=demand.provider_contract,
        ctf_event_id=demand.ctf_event_id,
        ctf_participant_id=demand.ctf_participant_id,
        objectives=list(demand.objectives),
        issuer_id=demand.issuer_id,
        provider_range_namespace=demand.provider_range_namespace,
        provider_participant_namespace=demand.provider_participant_namespace,
        key_mode=demand.key_mode.value,
        algorithm_id=demand.algorithm_id,
        key_id=demand.key_id,
        secret_version_ref=demand.secret_version_ref,
        public_verification_key=demand.public_verification_key,
        reset_generation=demand.reset_generation,
    )
    try:
        registration.full_clean()
        registration.save()
        _audit_registration(range_obj, registration, status="active")
    except (IntegrityError, ValidationError) as exc:
        raise ReceiptRegistrationConflict("receipt verifier registration conflicts with persisted state") from exc
    return _to_binding(registration)


def project_receipt_verifier_binding(
    request_id: UUID,
    *,
    owner_user_id: int,
    event_id: UUID,
    participant_id: UUID,
    profile_id: str,
    objective_id: str,
) -> ReceiptVerifierBinding:
    """Return the exact active binding, or fail closed on any context mismatch."""
    from engine.models import Range, ReceiptVerifierRegistration

    registration = (
        ReceiptVerifierRegistration.objects.select_related("range")
        .filter(
            range__request__request_id=request_id,
            range__status=Range.Status.READY,
            range__user_id=owner_user_id,
            status=ReceiptVerifierRegistration.Status.ACTIVE,
            ctf_event_id=event_id,
            ctf_participant_id=participant_id,
            profile_id=profile_id,
        )
        .first()
    )
    if registration is None or objective_id not in registration.objectives:
        raise ReceiptBindingUnavailable("no active receipt verifier binding matches the trusted context")
    if not _registration_integrity_holds(registration):
        raise ReceiptBindingUnavailable("receipt verifier registration no longer matches its materialization")
    return _to_binding(registration)


@transaction.atomic
def confirm_receipt_verifier_binding(
    request_id: UUID,
    *,
    owner_user_id: int,
    objective_id: str,
    expected: ReceiptVerifierBinding,
) -> None:
    """Lock and confirm an exact binding before its CTF solve commits."""
    from engine.models import Range, ReceiptVerifierRegistration

    range_obj = _locked_range(request_id)
    if range_obj.status != Range.Status.READY or range_obj.user_id != owner_user_id:
        raise ReceiptBindingUnavailable("receipt verifier binding is no longer active")
    registration = (
        ReceiptVerifierRegistration.objects.select_for_update()
        .filter(
            range=range_obj,
            status=ReceiptVerifierRegistration.Status.ACTIVE,
        )
        .first()
    )
    if (
        registration is None
        or objective_id not in registration.objectives
        or not _registration_integrity_holds(registration)
        or _to_binding(registration) != expected
    ):
        raise ReceiptBindingUnavailable("receipt verifier binding is no longer active")


@transaction.atomic
def revoke_receipt_verifier(request_id: UUID) -> bool:
    """Revoke the active verifier binding for a request, idempotently."""
    range_obj = _locked_range(request_id, required=False)
    if range_obj is None:
        return False
    return _revoke_receipt_verifier_for_range(range_obj)


def _revoke_receipt_verifier_for_range(range_obj: Range) -> bool:
    """Revoke a locked range's active registration inside the caller transaction."""
    from engine.models import ReceiptVerifierRegistration

    active = (
        ReceiptVerifierRegistration.objects.select_for_update()
        .filter(
            range=range_obj,
            status=ReceiptVerifierRegistration.Status.ACTIVE,
        )
        .first()
    )
    if active is None:
        return False
    active.status = ReceiptVerifierRegistration.Status.REVOKED
    active.revoked_at = timezone.now()
    active.save(update_fields=["status", "revoked_at", "updated_at"])
    _audit_registration(range_obj, active, status="revoked")
    return True


@overload
def _locked_range(request_id: UUID, *, required: Literal[True] = True) -> Range:
    """Return the required locked range."""
    ...


@overload
def _locked_range(request_id: UUID, *, required: Literal[False]) -> Range | None:
    """Return an optional locked range."""
    ...


def _locked_range(request_id: UUID, *, required: bool = True) -> Range | None:
    """Resolve and lock the unique Engine range correlated to ``request_id``."""
    from engine.models import Range

    ranges = list(Range.objects.select_for_update().filter(request__request_id=request_id)[:2])
    if len(ranges) == 1:
        return ranges[0]
    if not ranges and not required:
        return None
    if not ranges:
        raise ReceiptBindingUnavailable("no range exists for the receipt registration request")
    raise ReceiptRegistrationConflict("more than one range correlates to the receipt registration request")


def _registration_matches(
    registration: ReceiptVerifierRegistration,
    range_obj: Range,
    demand: ReceiptRegistrationDemand,
) -> bool:
    """Return whether an active row is an exact idempotent retry of ``demand``."""
    persisted = (
        registration.materialization_id,
        registration.provisioning_operation_id,
        registration.deployment_id,
        registration.profile_id,
        registration.provider_contract,
        registration.ctf_event_id,
        registration.ctf_participant_id,
        tuple(registration.objectives),
        registration.issuer_id,
        registration.provider_range_namespace,
        registration.provider_participant_namespace,
        registration.key_mode,
        registration.algorithm_id,
        registration.key_id,
        registration.secret_version_ref,
        registration.public_verification_key,
        registration.reset_generation,
    )
    requested = (
        range_obj.uuid,
        range_obj.provisioner_operation_id,
        demand.deployment_id,
        demand.profile_id,
        demand.provider_contract,
        demand.ctf_event_id,
        demand.ctf_participant_id,
        demand.objectives,
        demand.issuer_id,
        demand.provider_range_namespace,
        demand.provider_participant_namespace,
        demand.key_mode.value,
        demand.algorithm_id,
        demand.key_id,
        demand.secret_version_ref,
        demand.public_verification_key,
        demand.reset_generation,
    )
    return persisted == requested


def _registration_integrity_holds(registration: ReceiptVerifierRegistration) -> bool:
    """Reject a stale or corrupted projection even if its context fields match."""
    structurally_current = (
        registration.materialization_id == registration.range.uuid
        and registration.provisioning_operation_id == registration.range.provisioner_operation_id
        and bool(registration.provider_range_namespace)
        and bool(registration.provider_participant_namespace)
    )
    if not structurally_current:
        return False
    try:
        _to_binding(registration)
    except ValueError:
        return False
    return True


def _to_binding(registration: ReceiptVerifierRegistration) -> ReceiptVerifierBinding:
    """Build the secret-free downstream projection from one persisted row."""
    return ReceiptVerifierBinding(
        registration_revision=registration.registration_revision,
        materialization_id=registration.materialization_id,
        assignment_epoch=registration.assignment_epoch,
        deployment_id=registration.deployment_id,
        profile_id=registration.profile_id,
        provider_contract=registration.provider_contract,
        ctf_event_id=registration.ctf_event_id,
        ctf_participant_id=registration.ctf_participant_id,
        objectives=tuple(registration.objectives),
        issuer_id=registration.issuer_id,
        key_mode=ReceiptKeyMode(registration.key_mode),
        algorithm_id=registration.algorithm_id,
        key_id=registration.key_id,
        public_verification_key=registration.public_verification_key,
        provider_range_namespace=registration.provider_range_namespace,
        provider_participant_namespace=registration.provider_participant_namespace,
        reset_generation=registration.reset_generation,
    )


def _audit_registration(
    range_obj: Range,
    registration: ReceiptVerifierRegistration,
    *,
    status: str,
) -> None:
    """Commit bounded security-state evidence with registration mutations."""
    from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, audit_log

    request = range_obj.request
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=range_obj.pk,
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.SYSTEM,
            new_state={
                "receipt_registration_revision": str(registration.registration_revision),
                "receipt_provisioning_operation_id": str(registration.provisioning_operation_id),
                "receipt_profile": registration.profile_id,
                "receipt_key_mode": registration.key_mode,
                "receipt_algorithm": registration.algorithm_id,
                "receipt_key_id": registration.key_id,
                "receipt_reset_generation": registration.reset_generation,
                "receipt_status": status,
            },
            context="receipt_verifier_registration",
            request_id=str(request.request_id) if request is not None else "",
        ),
        strict=True,
    )
