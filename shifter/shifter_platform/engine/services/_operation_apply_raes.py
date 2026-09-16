"""Authoritative apply for RAES operation results (ADR-043 phase 5, #1837).

``_operation_apply_domain`` routes here once a result has been admitted
(envelope, discriminators, contract version, digest, generation, ownership,
conflict, ordering). This module owns what an applied RAES observation implies:
the sidecar evidence record, and -- for the steps that carry a lifecycle
projection -- the Range status transition, its strict audit row, and the ADR-025
notification.

Everything commits inside the caller's transaction, so a sidecar validation
failure, an audit failure, or an outbox failure rolls the whole result back and
leaves the inbox row retryable.

Two things this deliberately does NOT do:

* It does not call ``engine.services.project_raes_operation_status`` or
  ``record_raes_operation_status``. Those are the pre-cutover event-consumer
  path: the first enqueues a second outbox workflow, and both separate the
  sidecar write from the result disposition. Their persisters in
  ``shared.raes.operations`` are reused directly instead, so evidence and
  disposition share one transaction.
* It does not derive any timestamp from the wall clock. The sidecar's
  idempotency key is ``<kind>:<operation_id>:<source_timestamp>``, so a
  re-applied row must reproduce the same instant or a replay would fork into a
  second record. The inbox row's ``created_at`` is that stable instant.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from shared.audit import AuditEntityType
from shared.enums import ResourceStatus
from shared.operation_results import ResultStep, range_status_for
from shared.raes.status import RAES_STATE_FAILED

from ._operation_apply_effects import _audit, _enqueue_range_status_event, _save_status, _terminal_timestamps

if TYPE_CHECKING:
    from engine.models import OperationResultInbox, Range, WarmRangeGeneration

logger = logging.getLogger(__name__)


class RaesRealizedAccessError(Exception):
    """A realized access projection contradicts the immutable declaration (#1710).

    A permanent contract violation, not a transient failure: the dispatcher
    maps it to ``REJECTED_INVALID`` so the row is refused once rather than
    retried forever against state that can never satisfy it.
    """


# Steps whose evidence is a runtime snapshot rather than an operation status.
_SNAPSHOT_STEPS = frozenset({ResultStep.RAES_PROVISION_SNAPSHOT})

#: The shared terminal-failure writer owned by ``_operation_apply_domain``.
#: Passed in rather than imported so this module does not depend back on its
#: dispatcher: ``(target, payload, request_id, *, is_range) -> detail``.
ApplyFailure = Callable[..., str]


def _sidecar_payload(row: OperationResultInbox, **extra: Any) -> dict[str, Any]:
    """Build the common sidecar payload keys for one result.

    Mirrors the shape the pre-cutover ``range.raes.operation`` /
    ``range.raes.snapshot`` consumers produced, so historical and new evidence
    rows stay readable through the same Mission Control projections.
    """
    return {
        "operation_id": str(row.operation_id),
        "request_id": str(row.request_id),
        **extra,
    }


def _persist_operation_status(row: OperationResultInbox, state: str, status_reason: str | None) -> None:
    """Persist one RAES ``operation_status`` sidecar record for this result."""
    # Lazy import: shared.raes.operations pulls shared.models, which must not
    # load during Django app population (AppRegistryNotReady) -- the same
    # constraint _raes_evidence and _raes_range already observe.
    from shared.raes.operations import persist_operation_status_record

    source_timestamp = row.created_at
    payload = _sidecar_payload(row, status=state, source_timestamp=source_timestamp.isoformat())
    if status_reason:
        payload["status_reason"] = status_reason
    persist_operation_status_record(
        request_id=row.request_id,
        operation_id=str(row.operation_id),
        source_timestamp=source_timestamp,
        payload=payload,
    )


def _persist_runtime_snapshot(row: OperationResultInbox, resources: list[dict[str, Any]]) -> None:
    """Persist one RAES ``runtime_snapshot`` sidecar record for this result."""
    from shared.raes.operations import persist_runtime_snapshot_record

    source_timestamp = row.created_at
    persist_runtime_snapshot_record(
        request_id=row.request_id,
        operation_id=str(row.operation_id),
        source_timestamp=source_timestamp,
        payload=_sidecar_payload(row, resources=resources, captured_at=source_timestamp.isoformat()),
    )


def _apply_lifecycle(range_obj: Range, new_status: str, request_id: str) -> str:
    """Apply an RAES range transition with its audit row and notification."""
    extra = _terminal_timestamps(new_status)
    if new_status == ResourceStatus.READY.value:
        extra = {**extra, "ready_at": timezone.now()}
    previous = _save_status(range_obj, new_status, extra)
    if new_status in {ResourceStatus.DESTROYED.value, ResourceStatus.FAILED.value}:
        from ._receipt import _revoke_receipt_verifier_for_range

        _revoke_receipt_verifier_for_range(range_obj)
    _audit(AuditEntityType.RANGE, range_obj.id, new_status, request_id=request_id, previous={"status": previous})
    _enqueue_range_status_event(range_obj, new_status, "")
    return f"raes range -> {new_status}"


def _apply_observation(row: OperationResultInbox, step: ResultStep, payload: dict[str, Any], range_obj: Range) -> str:
    """Record an RAES observation and apply the range status it projects, if any."""
    _persist_operation_status(row, payload["raes_status"], payload.get("status_reason"))
    new_status = range_status_for(row.resource, row.operation, step=step)
    if new_status is None:
        return f"raes {payload['raes_status']} (evidence only)"
    return _apply_lifecycle(range_obj, new_status, str(row.request_id))


def _declared_access(range_obj: Range) -> set[tuple[str, str]]:
    """Return this range's immutable ``(target_address, channel)`` declarations."""
    from engine.models import RaesParticipantAccessBinding

    return {(row.target_address, row.channel) for row in RaesParticipantAccessBinding.objects.filter(range=range_obj)}


def _expected_member_endpoints(declared: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Return the exact ``(member uuid, channel)`` pairs a realization may claim.

    The provisioner-side join already refused any interactive target that does
    not materialize exactly one instance, so the only member that may carry a
    declared channel is that node's instance ``#0``. Naming the expected uuid
    here -- rather than reducing a member back to its node address -- is what
    stops a second instance (``node#1``), an invented suffix (``node#99``), or a
    duplicated endpoint from satisfying the gate.
    """
    return {(f"{target}#0", channel) for target, channel in declared}


def _realized_member_endpoints(members: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return every ``(member uuid, channel)`` the realization claims, with repeats."""
    return [(str(member["uuid"]), channel) for member in members for channel in member["participant_access_channels"]]


def _validated_member_endpoints(members: list[dict[str, Any]], range_obj: Range) -> None:
    """Require the realized endpoints to be exactly the declared ones.

    Equality is checked over member identity, not node address, and duplicates
    are rejected before the comparison: a set alone would collapse two members
    claiming the same channel into one pair and admit both.
    """
    realized = _realized_member_endpoints(members)
    duplicates = sorted({endpoint for endpoint in realized if realized.count(endpoint) > 1})
    if duplicates:
        raise RaesRealizedAccessError(f"raes realized participant access repeats endpoint(s): {duplicates[:3]}")
    if set(realized) != _expected_member_endpoints(_declared_access(range_obj)):
        raise RaesRealizedAccessError("raes realized participant access does not match the declared binding")


def _provisioned_instance(member: dict[str, Any]) -> dict[str, Any]:
    """Project one realized member into the portal's instance record."""
    instance = {
        "uuid": member["uuid"],
        "name": member["name"],
        "asset_type": "gce_vm",
        "role": "raes-node",
        "os_type": member["os_type"],
        "subnet_name": member["subnet_name"],
        "instance_id": member["instance_id"],
        "private_ip": member["private_ip"],
        "participant_access_channels": list(member["participant_access_channels"]),
        "participant_access_usernames": dict(member["participant_access_usernames"]),
        "ssh_key_secret_arn": member.get("ssh_key_secret_arn", ""),
        "rdp_password_secret_arn": member.get("rdp_password_secret_arn", ""),
        "gcp_host_public_key": member.get("host_public_key", ""),
        "cloud_provider": "gcp",
    }
    # Per-image Guacamole SFTP root (#375), when the realized member declared one.
    sftp_root_directory = member.get("sftp_root_directory")
    if sftp_root_directory:
        instance["sftp_root_directory"] = sftp_root_directory
    return instance


def _apply_ready_with_realized_access(
    row: OperationResultInbox,
    payload: dict[str, Any],
    range_obj: Range,
) -> str:
    """Persist this generation's realized access and transition READY atomically.

    The projection travels in the terminal result itself (ADR-032-R10), so the
    member state written here is always the one this operation generation
    produced -- there is no window in which an earlier generation's persisted
    state could satisfy the gate. Everything below commits in the caller's single
    transaction: a validation failure rolls back the status change with it.
    Only secret *references* are persisted; no credential value reaches this row.
    """
    members = payload["members"]
    _validated_member_endpoints(members, range_obj)
    range_obj.provisioned_instances = [_provisioned_instance(member) for member in members]
    range_obj.save(update_fields=["provisioned_instances", "updated_at"])
    logger.info(
        "raes realized access applied: request_id=%s members=%d",
        row.request_id,
        len(members),
    )
    return _apply_observation(row, ResultStep.RAES_TERMINAL_READY, payload, range_obj)


def _generation_cancelled(row: OperationResultInbox) -> bool:
    """Return True when this provision generation has an active cancellation (#277).

    A cancelled provision generation is fenced from authoritative lifecycle writes:
    its results are recorded as evidence but must never move the range out of
    DESTROYING (no PROVISIONING/READY/FAILED, no provisioned state). Once the
    launcher enqueues the canonical destroy the generation also becomes stale by
    ``operation_id`` and is rejected earlier; this closes the window before that.
    """
    from engine.models import InterruptState, ProvisionerLaunchIntent

    state = (
        ProvisionerLaunchIntent.objects.filter(operation_id=row.operation_id)
        .values_list("interrupt_state", flat=True)
        .first()
    )
    return bool(state) and state != InterruptState.NONE


def _apply_cancelled_evidence(row: OperationResultInbox, step: ResultStep, payload: dict[str, Any]) -> str:
    """Record a cancelled generation's result as evidence only -- no lifecycle write."""
    if step is ResultStep.RAES_TERMINAL_FAILED:
        _persist_operation_status(row, RAES_STATE_FAILED, payload["reason_code"])
    else:
        _persist_operation_status(row, payload["raes_status"], payload.get("status_reason"))
    return f"raes {step.value} fenced (cancelled generation, evidence only)"


def apply_raes_result(
    row: OperationResultInbox,
    step: ResultStep,
    payload: dict[str, Any],
    range_obj: Range,
    apply_failure: ApplyFailure,
) -> str:
    """Apply one admitted RAES provision/destroy result. Caller holds the lock.

    ``apply_failure`` is the shared terminal-failure writer from
    ``_operation_apply_domain``; failure handling is identical across families
    (authored reason code onto the row, generation cleared, audit, notification)
    and is not reimplemented here.
    """
    if step in _SNAPSHOT_STEPS:
        # Bounded evidence only: no status write, no audit row, no range event.
        _persist_runtime_snapshot(row, payload["resources"])
        return f"raes snapshot ({len(payload['resources'])} resource(s))"

    # Fence a cancelled provision generation (#277): record evidence, never write
    # lifecycle state that would regress the range out of DESTROYING. Destroy
    # results carry their own (uncancelled) generation, so they are unaffected.
    if _generation_cancelled(row):
        return _apply_cancelled_evidence(row, step, payload)
    return _apply_uncancelled_raes_result(row, step, payload, range_obj, apply_failure)


def _apply_uncancelled_raes_result(
    row: OperationResultInbox,
    step: ResultStep,
    payload: dict[str, Any],
    range_obj: Range,
    apply_failure: ApplyFailure,
) -> str:
    """Apply a RAES result that is not fenced by a cancellation."""
    if step is ResultStep.RAES_TERMINAL_FAILED:
        # The sidecar still records the failed observation; only the closed
        # reason code travels as its reason, never the bounded diagnostic.
        _persist_operation_status(row, RAES_STATE_FAILED, payload["reason_code"])
        # A failed warm-prepare or activation must move the ledger to a
        # reconciler-owned retiring state, not just fail the range (#28): the
        # reconciler then destroys and cleans it up. Non-warm ranges are unaffected.
        _retire_warm_generation_on_failure(row, range_obj)
        return apply_failure(range_obj, payload, str(row.request_id), is_range=True)

    if step is ResultStep.RAES_TERMINAL_READY:
        return _apply_terminal_ready(row, payload, range_obj)

    if step is ResultStep.RAES_TERMINAL_DESTROYED:
        # Record scoped provider inventory/readback evidence BEFORE the DESTROYED
        # transition so verified_terminal, pruning, and CTF capacity release gate on
        # it, not on the logical status (#2086, ADR-063-R4/R5). Same transaction.
        _record_cleanup_inventory(row, payload)

    return _apply_observation(row, step, payload, range_obj)


def _record_cleanup_inventory(row: OperationResultInbox, payload: dict[str, Any]) -> None:
    """Record the terminal destroy's scoped inventory/readback evidence, if present."""
    inventory = payload.get("cleanup_inventory")
    if not isinstance(inventory, dict) or "outcome" not in inventory:
        return
    from ._cleanup_verification import record_cleanup_verification

    record_cleanup_verification(
        request_id=str(row.request_id),
        operation_id=str(row.operation_id),
        outcome=str(inventory["outcome"]),
        scope=dict(inventory.get("scope") or {}),
        residual_categories=list(inventory.get("residual_categories") or []),
        observed_at=row.created_at,
    )


def _validate_completion(row: OperationResultInbox, payload: dict[str, Any], range_obj: Range) -> None:
    """Admit current evidence against the exact generation's immutable input."""
    from engine.models import OperationInput
    from shared.raes.completion import completed_snapshot, load_serialized_plan

    try:
        record = OperationInput.objects.filter(operation_id=row.operation_id, request_id=row.request_id).first()
        if record is None:
            config = range_obj.range_config
            if isinstance(config, dict) and config.get("contract_version") == "raes-provisioning-plan-v2":
                raise ValueError("missing immutable input")
            # Historical result tests/records without the new transport.
            return
        immutable = record.envelope["payload"]
        if row.operation == "activate":
            immutable = immutable["raes_input"]
        if (immutable["plan"].get("contract_version"), immutable["plan"].get("raes_version")) == (
            "raes-provisioning-plan-v1",
            "2.0.0",
        ):
            # In-flight old producer results retain their historical contract.
            return
        completed_snapshot(
            load_serialized_plan(immutable["plan"]),
            payload["completion"],
            generation_id=str(row.operation_id),
            serialized_plan=immutable["plan"],
        )
    except (KeyError, TypeError, ValueError):
        raise RaesRealizedAccessError("realization completion evidence is missing or invalid") from None


def _apply_terminal_ready(row: OperationResultInbox, payload: dict[str, Any], range_obj: Range) -> str:
    """Apply a RAES terminal-READY result, branching warm-prepare vs cold/activation."""
    _validate_completion(row, payload, range_obj)
    pending = _pending_warm_generation(row, range_obj)
    if pending is not None:
        # Warm-prepare terminal: the infrastructure is realized, but the range
        # is system-owned with no participant access. It must NOT become public
        # READY (that would let a claimant race access surfaces before
        # activation scrubs); it stays quarantined until activation. The pool
        # tracks readiness on the ledger row, not on Range.status (#28).
        return _apply_warm_prepared(row, payload, range_obj, pending)
    # Normal cold provision, or a warm activation: transition to READY with the
    # (claimant) realized access.
    detail = _apply_ready_with_realized_access(row, payload, range_obj)
    # A successful warm activation settles the claimed ledger row to ACTIVATED
    # (consumed; the range is now the claimant's live range). Capacity stays held
    # while the range exists and is released when the range is destroyed (#28).
    _settle_warm_generation_on_activation(row, range_obj)
    return detail


def _settle_warm_generation_on_activation(row: OperationResultInbox, range_obj: Range) -> None:
    """Move a CLAIMED warm generation to ACTIVATED when its activation succeeds (#28)."""
    if row.operation != "activate":
        return
    from engine.models import WarmRangeGeneration

    request_id = getattr(getattr(range_obj, "request", None), "request_id", None)
    if request_id is None:
        return
    gen = (
        WarmRangeGeneration.objects.select_for_update()
        .filter(request_id=request_id, state=WarmRangeGeneration.State.CLAIMED)
        .first()
    )
    if gen is None:
        return
    gen.state = WarmRangeGeneration.State.ACTIVATED
    gen.save(update_fields=["state"])
    logger.info("warm generation activated (consumed): request_id=%s", row.request_id)


def _pending_warm_generation(row: OperationResultInbox, range_obj: Range) -> WarmRangeGeneration | None:
    """Return the PROVISIONING warm ledger row for this request, or None.

    Only a ``provision`` operation can be a warm-prepare; an ``activate`` result
    finds no PROVISIONING row (the row is CLAIMED) and takes the normal READY path.
    """
    if row.operation != "provision":
        return None
    from engine.models import WarmRangeGeneration

    request_id = getattr(getattr(range_obj, "request", None), "request_id", None)
    if request_id is None:
        return None
    return (
        WarmRangeGeneration.objects.select_for_update()
        .filter(request_id=request_id, state=WarmRangeGeneration.State.PROVISIONING)
        .first()
    )


def _apply_warm_prepared(
    row: OperationResultInbox, payload: dict[str, Any], range_obj: Range, gen: WarmRangeGeneration
) -> str:
    """Realize a warm-prepared generation: persist infra, keep quarantined, flip ledger READY.

    Persists the realized instance projection and the succeeded sidecar observation,
    but deliberately leaves ``Range.status`` unchanged (PROVISIONING) so no public
    access resolver serves the range. The pool becomes able to claim it only when
    this ledger row flips to READY.
    """
    from django.utils import timezone

    from engine.models import WarmRangeGeneration

    members = payload["members"]
    _validated_member_endpoints(members, range_obj)
    range_obj.provisioned_instances = [_provisioned_instance(member) for member in members]
    range_obj.save(update_fields=["provisioned_instances", "updated_at"])
    # Record the succeeded observation as sidecar evidence only (no range status
    # transition): warm-prepare terminal does not publish READY.
    _persist_operation_status(row, payload["raes_status"], payload.get("status_reason"))
    gen.state = WarmRangeGeneration.State.READY
    gen.range = range_obj
    gen.ready_at = timezone.now()
    gen.operation_id = row.operation_id
    gen.save(update_fields=["state", "range", "ready_at", "operation_id"])
    logger.info("warm generation ready (quarantined): request_id=%s", row.request_id)
    return "raes warm-prepare -> pool-ready (quarantined)"


def _retire_warm_generation_on_failure(row: OperationResultInbox, range_obj: Range) -> None:
    """Move a failed warm generation (prepare or activate) to RETIRING for cleanup (#28)."""
    from engine.models import WarmRangeGeneration

    request_id = getattr(getattr(range_obj, "request", None), "request_id", None)
    if request_id is None:
        return
    gen = (
        WarmRangeGeneration.objects.select_for_update()
        .filter(
            request_id=request_id,
            state__in=(WarmRangeGeneration.State.PROVISIONING, WarmRangeGeneration.State.CLAIMED),
        )
        .first()
    )
    if gen is None:
        return
    # UNHEALTHY (not RETIRING): a failed prepare/activation may have realized fresh
    # credentials or access paths, so the reconciler must actively dispatch destroy
    # for it. RETIRING already assumes a destroy was requested; using it here would
    # leave the generation waiting for a teardown that never runs (#28).
    gen.state = WarmRangeGeneration.State.UNHEALTHY
    gen.save(update_fields=["state"])
    logger.info("warm generation moved to unhealthy on failure: request_id=%s", row.request_id)
