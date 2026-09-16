"""Engine-owned result applier for the operation result inbox (ADR-043).

Claims PENDING ``OperationResultInbox`` rows, validates each against the current
domain operation generation, ownership, contract version, and payload digest,
then dispatches declared operation families to the authoritative domain applier.
Domain state, applied-transition audit, result disposition, and any
``RangeEventOutbox`` row share one transaction. Compatibility families without a
declared step contract remain validation-only shadow results until their direct
provisioner SQL path is removed.

The generation fence is the whole point: a result is tagged with the exact
``operation_id`` its provisioner run was launched for, so a result whose operation
generation is no longer current on the domain row is rejected as stale rather than
silently applied to a newer lifecycle episode.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from shared.operation_envelope import (
    ACCEPTED_CONTRACT_VERSIONS,
    OperationEnvelopeError,
    canonical_payload_digest,
    validate_operation_envelope,
)

from ._operation_apply_domain import apply_validated_result

# engine.models is imported lazily inside functions below (app-registry load
# order); this block is type-check-only.
if TYPE_CHECKING:
    from engine.models import Instance, OperationResultInbox, Range

logger = logging.getLogger(__name__)

_RANGE_RESOURCES = frozenset({"range", "raes-range"})


def _resolve_operation_target(resource: str, operation_id: UUID | str) -> Range | Instance | None:
    """Return the domain row that currently owns this operation generation, or None.

    A row is returned only when its ``provisioner_operation_id`` still equals the
    result's ``operation_id`` — i.e. the generation is current. A rotated (or
    absent) generation resolves to None, which the caller treats as stale.
    """
    from engine.models import Instance, Range

    if resource in _RANGE_RESOURCES:
        return Range.objects.filter(provisioner_operation_id=operation_id).select_related("request").first()
    if resource == "ngfw":
        return (
            Instance.objects.filter(provisioner_operation_id=operation_id, role=Instance.Role.NGFW)
            .select_related("request")
            .first()
        )
    return None


def _request_matches(target: Range | Instance, expected_request_id: object) -> bool:
    """Return True if the target row's request matches the result's request_id."""
    request = getattr(target, "request", None)
    actual_request_id = getattr(request, "request_id", None)
    return actual_request_id is not None and str(actual_request_id) == str(expected_request_id)


def evaluate_operation_result(row: OperationResultInbox) -> tuple[str, str]:
    """Return ``(disposition, detail)`` for one inbox row. Pure: no mutation.

    Fails closed, in order, on any of: invalid envelope, unsupported contract
    version, digest mismatch, stale operation generation, or wrong resource
    ownership. The first failing check wins; a single exit returns the verdict.
    """
    from engine.models import OperationResultDisposition

    try:
        envelope = validate_operation_envelope(row.envelope)
    except OperationEnvelopeError as exc:
        return OperationResultDisposition.REJECTED_INVALID, str(exc)[:128]

    if row.contract_version not in ACCEPTED_CONTRACT_VERSIONS:
        result = (
            OperationResultDisposition.REJECTED_VERSION,
            f"unsupported contract_version {row.contract_version}"[:128],
        )
    elif canonical_payload_digest(envelope["payload"]) != row.payload_digest:
        result = (
            OperationResultDisposition.REJECTED_CONFLICT,
            "stored payload digest does not match the envelope payload",
        )
    elif (target := _resolve_operation_target(row.resource, row.operation_id)) is None:
        result = (
            OperationResultDisposition.REJECTED_STALE,
            "operation generation is no longer current",
        )
    elif not _request_matches(target, row.request_id):
        result = (
            OperationResultDisposition.REJECTED_OWNERSHIP,
            "result request does not match the operation target",
        )
    else:
        result = (OperationResultDisposition.VALIDATED, "")
    return result


def apply_pending_operation_results(*, batch_size: int = 50) -> int:
    """Claim and apply a batch of PENDING inbox results.

    Claims with ``select_for_update(skip_locked=True)`` so concurrent appliers do
    not contend. Declared operation families are applied authoritatively; other
    families receive a validation-only shadow disposition. Returns the number of
    rows dispositioned.
    """
    from engine.models import OperationResultDisposition, OperationResultInbox

    evaluated = 0
    with transaction.atomic():
        rows = list(
            OperationResultInbox.objects.select_for_update(skip_locked=True)
            .filter(disposition=OperationResultDisposition.PENDING)
            .order_by("created_at")[:batch_size]
        )
        for row in rows:
            disposition, detail = evaluate_operation_result(row)
            if disposition == OperationResultDisposition.VALIDATED:
                # Admissible: hand to the authoritative apply, which locks the
                # target and commits domain state, audit, and notification inside
                # this same transaction.
                disposition, detail = apply_validated_result(row)
                if not disposition:
                    # Deliberately deferred: an earlier result of the same
                    # operation generation is still pending, so this one stays
                    # PENDING for a later pass rather than jumping ahead of it.
                    continue
            row.disposition = disposition
            row.disposition_detail = detail
            row.applied_at = timezone.now()
            row.save(update_fields=["disposition", "disposition_detail", "applied_at"])
            evaluated += 1
    return evaluated
