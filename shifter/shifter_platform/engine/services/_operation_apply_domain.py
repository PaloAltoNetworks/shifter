"""Authoritative domain apply for validated operation results (ADR-043 phase 4, #1836).

``_operation_apply`` decides whether an inbox row is *admissible* (envelope,
contract version, digest, generation, ownership). This module decides whether it
is *applicable* — discriminators agree, the step is declared, the payload parses,
no conflicting sibling exists, the step legally follows what has already been
applied — and then performs the write.

Everything the applied transition implies commits together inside the caller's
``transaction.atomic()``: the domain rows, a **strict** audit row (ADR-043-R3 —
best-effort auditing is not sufficient when the audit row is the control), and
the ADR-025 ``RangeEventOutbox`` notification. A failure anywhere rolls the whole
result back and leaves the inbox row retryable rather than half-applied.

The provisioner is no longer an authoritative writer for this family: one
operation generation has exactly one authoritative path, and it is this one.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.utils import timezone

from shared.audit import AuditEntityType
from shared.enums import ResourceStatus
from shared.operation_envelope import OperationEnvelopeError, validate_operation_envelope
from shared.operation_results import (
    OperationResultError,
    ResultStep,
    has_contract,
    latest_step,
    parse_result_payload,
    result_kind_for,
    step_follows,
)

from ._operation_apply_admission import (
    applied_steps,
    discriminator_mismatch,
    has_conflicting_sibling,
    has_earlier_pending_sibling,
)
from ._operation_apply_effects import (
    _audit,
    _enqueue_ngfw_status_event,
    _enqueue_range_status_event,
    _save_status,
    _terminal_timestamps,
)

if TYPE_CHECKING:
    from engine.models import Instance, OperationResultInbox, Range

    from ._operation_apply_raes import RaesRealizedAccessError

logger = logging.getLogger(__name__)

_RANGE_RESOURCES = frozenset({"range", "raes-range"})

# RAES-native lifecycle operations (ADR-043 phase 5, #1837). Pause/resume are
# deliberately absent: they share the generic range step tables and dispatch.
_RAES_OPERATIONS = frozenset({("raes-range", "provision"), ("raes-range", "destroy"), ("raes-range", "activate")})

# Range steps that settle the generation, whether it failed or reached a
# paused/ready outcome.
_RANGE_TERMINAL_STEPS = frozenset(
    {ResultStep.RANGE_TERMINAL_FAILED, ResultStep.RANGE_TERMINAL_PAUSED, ResultStep.RANGE_TERMINAL_READY}
)

# Statuses on another attached range that keep a shared NGFW running. The
# provisioner's ``should_pause_ngfw`` is a pre-cloud compatibility check; this
# re-check under lock is the authorization.
_NGFW_KEEP_ALIVE_STATUSES = (ResourceStatus.READY.value, ResourceStatus.RESUMING.value)


def _lock_range(operation_id: UUID | str) -> Range | None:
    """Lock and return the Range that currently owns this operation generation.

    No ``select_related`` here on purpose: ``Range.ngfw_instance`` is nullable, and
    PostgreSQL refuses ``SELECT ... FOR UPDATE`` over the nullable side of an outer
    join. Related rows are resolved afterwards and locked explicitly, in the
    declared primary-key order, by the paths that mutate them.
    """
    from engine.models import Range

    return Range.objects.select_for_update().filter(provisioner_operation_id=operation_id).first()


def _lock_ngfw_instance(operation_id: UUID | str) -> Instance | None:
    """Lock and return the NGFW Instance that currently owns this generation."""
    from engine.models import Instance

    return (
        Instance.objects.select_for_update()
        .filter(provisioner_operation_id=operation_id, role=Instance.Role.NGFW)
        .first()
    )


def _lock_instance_by_pk(pk: int) -> Instance | None:
    """Lock one Instance row explicitly (used after a nullable FK is resolved)."""
    from engine.models import Instance

    return Instance.objects.select_for_update().filter(pk=pk).first()


def _apply_instances(range_obj: Range, payload: dict[str, Any], request_id: str) -> str:
    """Apply a bounded set of instance outcomes belonging to this Range's request.

    Locked in primary-key order, and matched against the closed UUID set the
    result carries — never a blanket update of every instance for the request.
    """
    from engine.models import Instance

    wanted = {outcome["instance_uuid"]: outcome["status"] for outcome in payload["instances"]}
    # The permitted set is derived server-side from the locked Range's request,
    # and NGFW-role instances are excluded outright: a shared NGFW may only move
    # through the cascade path, which checks attachment and whether another
    # attached Range still needs it. Without this exclusion an inbox INSERT --
    # the provisioner principal's one remaining capability -- could name the
    # attached NGFW in an ordinary instance result and bypass both checks.
    rows = list(
        Instance.objects.select_for_update()
        .filter(request=range_obj.request, uuid__in=list(wanted))
        .exclude(role=Instance.Role.NGFW)
        .order_by("pk")
    )
    found = {str(row.uuid) for row in rows}
    missing = sorted(set(wanted) - found)
    if missing:
        raise _NotApplicable(f"result names {len(missing)} instance(s) outside the operation's lifecycle target set")

    applied = []
    for row in rows:
        new_status = wanted[str(row.uuid)]
        previous = _save_status(row, new_status)
        applied.append({"instance_uuid": str(row.uuid), "previous": previous})

    # One audit row for the transition, against the Range that owns it: the
    # instances share a status and an operation generation, and their identity is
    # UUID-based (not a valid AuditLog.entity_id).
    _audit(
        AuditEntityType.RANGE,
        range_obj.id,
        payload["instances"][0]["status"],
        request_id=request_id,
        previous={"instances": applied},
        detail={"instance_count": len(rows)},
    )
    return f"{len(rows)} instance(s)"


def _resolve_cascade_ngfw(range_obj: Range, payload: dict[str, Any]) -> Instance:
    """Resolve the NGFW a Range operation may cascade to, or refuse.

    Ownership runs through ``Range.ngfw_instance`` — never through a
    payload-supplied id — so one Range generation cannot mutate an arbitrary
    NGFW.
    """
    if range_obj.ngfw_instance_id is None:
        raise _NotApplicable("range has no attached NGFW to cascade to")
    # Resolve through the FK, then take the row lock explicitly: the owning Range
    # is already locked, so this is the second lock in the declared order.
    ngfw = _lock_instance_by_pk(range_obj.ngfw_instance_id)
    if ngfw is None:
        raise _NotApplicable("attached NGFW no longer exists")
    if str(ngfw.uuid) != payload["ngfw_instance_uuid"]:
        raise _NotApplicable("result NGFW does not match the range's attached NGFW")
    return ngfw


def _other_attached_range_needs_ngfw(range_obj: Range, ngfw: Instance) -> bool:
    """Return True when another attached Range still needs this shared NGFW."""
    from engine.models import Range

    return (
        Range.objects.filter(ngfw_instance=ngfw, status__in=_NGFW_KEEP_ALIVE_STATUSES).exclude(pk=range_obj.pk).exists()
    )


def _apply_ngfw(ngfw: Instance, new_status: str, request_id: str) -> None:
    """Apply an NGFW Instance transition and its NGFW App projection."""
    from engine.models import App

    previous = _save_status(ngfw, new_status, _terminal_timestamps(new_status))

    # Only the NGFW App projection belongs to this lifecycle, never every App
    # beneath the instance.
    apps = list(App.objects.select_for_update().filter(instance=ngfw, app_type=App.AppType.NGFW).order_by("pk"))
    for app in apps:
        _save_status(app, new_status, _terminal_timestamps(new_status))

    _audit(
        AuditEntityType.NGFW,
        0,
        new_status,
        request_id=request_id,
        previous={"status": previous},
        detail={"instance_uuid": str(ngfw.uuid), "app_uuids": [str(app.uuid) for app in apps]},
    )
    _enqueue_ngfw_status_event(ngfw, apps[0] if apps else None, new_status, request_id)


class _NotApplicable(Exception):
    """A validated result that must not mutate this domain state."""


def _apply_range_terminal(range_obj: Range, payload: dict[str, Any], request_id: str) -> str:
    """Apply the terminal status of a Range pause/resume."""
    new_status = payload["status"]
    extra = {}
    if new_status == ResourceStatus.READY.value:
        extra["ready_at"] = timezone.now()
    if new_status == ResourceStatus.PAUSED.value:
        extra["paused_at"] = timezone.now()
    previous = _save_status(range_obj, new_status, extra)
    if new_status in {ResourceStatus.DESTROYED.value, ResourceStatus.FAILED.value}:
        from ._receipt import _revoke_receipt_verifier_for_range

        _revoke_receipt_verifier_for_range(range_obj)
    _audit(AuditEntityType.RANGE, range_obj.id, new_status, request_id=request_id, previous={"status": previous})
    _enqueue_range_status_event(range_obj, new_status, "")
    return f"range -> {new_status}"


def _apply_failure(target: Range | Instance, payload: dict[str, Any], request_id: str, is_range: bool) -> str:
    """Apply a terminal failure, carrying only the authored reason code."""
    from engine.launch_intents import clear_provisioner_operation_after_failure

    new_status = ResourceStatus.FAILED.value
    context = payload["reason_code"]
    previous = target.status
    now = timezone.now()
    target.status = new_status
    target.updated_at = now
    target.error_message = context  # type: ignore[union-attr]  # both models carry it
    update_fields = ["status", "updated_at", "error_message"]
    update_fields.extend(clear_provisioner_operation_after_failure(target))
    target.save(update_fields=update_fields)

    if is_range:
        from ._receipt import _revoke_receipt_verifier_for_range

        _revoke_receipt_verifier_for_range(cast("Range", target))
        _audit(
            AuditEntityType.RANGE,
            target.id,
            new_status,
            request_id=request_id,
            previous={"status": previous},
            context=context,
        )
    else:
        _audit(
            AuditEntityType.NGFW,
            0,
            new_status,
            request_id=request_id,
            previous={"status": previous},
            detail={"instance_uuid": str(target.uuid)},
            context=context,
        )
    if is_range:
        _enqueue_range_status_event(cast("Range", target), new_status, context)
    return f"{'range' if is_range else 'ngfw'} -> failed ({context})"


def _lock_operation_target(row: OperationResultInbox) -> Range | Instance | None:
    """Lock the domain row that owns this operation generation, or return None.

    Locking happens BEFORE any conflict or ordering decision. All results for one
    generation resolve to the same row, so this lock is the serialization
    boundary: two appliers claiming sibling results with ``skip_locked`` cannot
    evaluate history concurrently and both decide they may apply.
    """
    if row.resource in _RANGE_RESOURCES:
        return _lock_range(row.operation_id)
    return _lock_ngfw_instance(row.operation_id)


def _dispatch_range(row: OperationResultInbox, step: ResultStep, payload: dict[str, Any], target: Range) -> str:
    """Apply a range-resource result. Caller holds the Range lock."""
    request_id = str(row.request_id)
    if step in (ResultStep.RANGE_INSTANCES_PAUSED, ResultStep.RANGE_INSTANCES_READY):
        return _apply_instances(target, payload, request_id)
    if step in _RANGE_TERMINAL_STEPS:
        return _dispatch_range_terminal(step, payload, request_id, target)
    return _dispatch_cascade(target, payload, request_id)


def _dispatch_range_terminal(step: ResultStep, payload: dict[str, Any], request_id: str, target: Range) -> str:
    """Settle a range at a terminal step: failure, or a paused/ready outcome."""
    if step is ResultStep.RANGE_TERMINAL_FAILED:
        return _apply_failure(target, payload, request_id, is_range=True)
    return _apply_range_terminal(target, payload, request_id)


def _dispatch_cascade(range_obj: Range, payload: dict[str, Any], request_id: str) -> str:
    """Apply an NGFW cascade step, a subordinate result of the Range generation."""
    ngfw = _resolve_cascade_ngfw(range_obj, payload)
    new_status = payload["status"]
    pausing = new_status in (ResourceStatus.PAUSING.value, ResourceStatus.PAUSED.value)
    if pausing and _other_attached_range_needs_ngfw(range_obj, ngfw):
        raise _NotApplicable("another attached range still needs this NGFW")
    _apply_ngfw(ngfw, new_status, request_id)
    return f"ngfw cascade -> {new_status}"


def _dispatch_ngfw(row: OperationResultInbox, step: ResultStep, payload: dict[str, Any], target: Instance) -> str:
    """Apply a direct NGFW-resource result. Caller holds the Instance lock."""
    request_id = str(row.request_id)
    if step is ResultStep.NGFW_TERMINAL_FAILED:
        return _apply_failure(target, payload, request_id, is_range=False)
    if str(target.uuid) != payload["ngfw_instance_uuid"]:
        raise _NotApplicable("result NGFW does not match the operation target")
    _apply_ngfw(target, payload["status"], request_id)
    return f"ngfw -> {payload['status']}"


def _dispatch(row: OperationResultInbox, step: ResultStep, payload: dict[str, Any], target: Range | Instance) -> str:
    """Route one validated result to its domain write. Caller holds the lock."""
    if row.resource in _RANGE_RESOURCES:
        if (row.resource, row.operation) in _RAES_OPERATIONS:
            # RAES provision/destroy report operation observations and topology
            # evidence, not instance sets; pause/resume keep the range shape.
            from ._operation_apply_raes import apply_raes_result

            return apply_raes_result(row, step, payload, cast("Range", target), _apply_failure)
        return _dispatch_range(row, step, payload, cast("Range", target))
    return _dispatch_ngfw(row, step, payload, cast("Instance", target))


class _Rejected(Exception):
    """A deterministic refusal carrying the disposition to record."""

    def __init__(self, disposition: str, detail: str) -> None:
        super().__init__(detail)
        self.disposition = disposition
        self.detail = detail[:128]


def _admit(row: OperationResultInbox) -> tuple[ResultStep, dict[str, Any]]:
    """Return the step and parsed payload, or raise ``_Rejected``.

    Raising rather than returning a verdict per check keeps the caller to a
    single exit and keeps each guard a one-liner.
    """
    from engine.models import OperationResultDisposition

    try:
        envelope = validate_operation_envelope(row.envelope)
    except OperationEnvelopeError as exc:
        raise _Rejected(OperationResultDisposition.REJECTED_INVALID, str(exc)) from None

    mismatch = discriminator_mismatch(row, envelope)
    if mismatch:
        raise _Rejected(OperationResultDisposition.REJECTED_INVALID, mismatch)

    # Families not yet cut over stay in shadow: they have no authoritative
    # contract here and direct provisioner SQL is still their sole writer, so
    # applying (or rejecting) them would be wrong.
    if not has_contract(row.resource, row.operation):
        raise _Rejected(OperationResultDisposition.VALIDATED, "shadow: family not yet cut over")
    if not row.result_step:
        raise _Rejected(OperationResultDisposition.VALIDATED, "shadow: result predates the step contract")

    try:
        step = ResultStep(row.result_step)
        if result_kind_for(row.resource, row.operation, step=step) != row.result_kind:
            raise _Rejected(OperationResultDisposition.REJECTED_INVALID, "result_kind does not match the declared step")
        payload = parse_result_payload(row.resource, row.operation, step=step, payload=envelope["payload"])
    except ValueError:
        raise _Rejected(
            OperationResultDisposition.REJECTED_INVALID, f"unknown result step '{row.result_step}'"
        ) from None
    except OperationResultError as exc:
        raise _Rejected(OperationResultDisposition.REJECTED_INVALID, str(exc)) from None
    return step, payload


def _lock_and_authorize(row: OperationResultInbox, step: ResultStep) -> Range | Instance | None:
    """Lock the generation's target and check conflict + ordering under that lock.

    Returns None when the row should stay PENDING for a later pass. Raises
    ``_Rejected`` for a deterministic refusal.
    """
    from engine.models import OperationResultDisposition

    # Lock BEFORE deciding conflict or ordering. Every result for one operation
    # resolves to the same target, so this serializes sibling results: without it
    # two appliers can each read an empty applied history and both apply.
    target = _lock_operation_target(row)
    if target is None:
        raise _Rejected(OperationResultDisposition.REJECTED_STALE, "operation generation is no longer current")

    if has_conflicting_sibling(row):
        raise _Rejected(
            OperationResultDisposition.REJECTED_CONFLICT,
            "another result for this step carries a different payload",
        )

    # Do not advance past a still-pending earlier sibling. Claiming order is
    # created_at, but skip_locked lets a worker reach a later result first;
    # applying it would make the earlier step arrive "late" and be rejected.
    if has_earlier_pending_sibling(row):
        return None

    previous_step = latest_step(row.resource, row.operation, applied_steps(row))
    if not step_follows(row.resource, row.operation, previous=previous_step, step=step):
        raise _Rejected(OperationResultDisposition.REJECTED_ORDERING, f"step may not follow '{previous_step}'")
    return target


def apply_validated_result(row: OperationResultInbox) -> tuple[str, str]:
    """Apply one admissible inbox row to domain state. Returns ``(disposition, detail)``.

    The caller supplies the transaction; every write this makes is rolled back
    with it. Deterministic refusals return a disposition and mutate nothing.
    An empty disposition means "leave PENDING for a later pass". Transient
    failures propagate so the row stays retryable.
    """
    from engine.models import OperationResultDisposition

    from ._operation_apply_raes import RaesRealizedAccessError

    try:
        step, payload = _admit(row)
        target = _lock_and_authorize(row, step)
        if target is None:
            return "", ""
        detail = _dispatch(row, step, payload, target)
    except (_Rejected, _NotApplicable, RaesRealizedAccessError) as refusal:
        return _refusal_disposition(refusal)
    return OperationResultDisposition.APPLIED, detail[:128]


def _refusal_disposition(refusal: _Rejected | _NotApplicable | RaesRealizedAccessError) -> tuple[str, str]:
    """Map a deterministic refusal onto the disposition and detail to record."""
    from engine.models import OperationResultDisposition

    if isinstance(refusal, _Rejected):
        return refusal.disposition, refusal.detail
    if isinstance(refusal, _NotApplicable):
        return OperationResultDisposition.REJECTED_OWNERSHIP, str(refusal)[:128]
    # A realized/declared access mismatch can never be satisfied by a retry.
    return OperationResultDisposition.REJECTED_INVALID, str(refusal)[:128]
