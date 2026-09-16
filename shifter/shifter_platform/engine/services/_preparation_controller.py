"""Leased preparation reconciliation: cloud I/O outside fenced domain transactions."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from shared.audit import AuditAction
from shared.cloud import get_preparation_readback, get_preparation_task
from shared.cloud.preparation_runtime import PreparationTask
from shared.cloud.types import TaskInterruptDisposition
from shared.exceptions import ValidationError
from shared.operation_envelope import canonical_payload_digest
from shared.preparation_grant import PreparationGrantConfiguration
from shared.raes.prepared_artifacts import VerifiedMaterialization

from ._preparation_admission import save_admission, validated_result, verified_facts
from ._preparation_operations import _audit_operation, new_preparation_attempt
from ._preparation_worker import _current_attempt, attempt_token

_LEASE_SECONDS = 300
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from engine.models import PreparationAttempt, PreparationOperation


@contextmanager
def _locked(operation_id: UUID) -> Iterator[PreparationOperation]:
    """Same lock order as admission and grant/adapter administration."""
    from engine.models import PreparationAdapter, PreparationGrant, PreparationOperation, PreparationScopeLock

    with transaction.atomic():
        initial = PreparationOperation.objects.select_related("adapter").get(pk=operation_id)
        PreparationScopeLock.objects.select_for_update().get(pk=initial.scope_digest)
        PreparationGrant.objects.select_for_update().get(pk=initial.adapter.grant_id)
        PreparationAdapter.objects.select_for_update().get(pk=initial.adapter_id)
        yield PreparationOperation.objects.select_for_update().get(pk=operation_id)


def reconcile_preparations(*, limit: int = 20, scope_digest: str | None = None) -> int:
    """Bounded durable scan; no message delivery is necessary for eventual recovery."""
    from engine.models import PreparationOperation

    operations = PreparationOperation.objects.filter(
        Q(state__in=["queued", "running", "verifying"]) | Q(cleanup_pending=True)
    )
    if scope_digest is not None:
        operations = operations.filter(scope_digest=scope_digest)
    identities = list(operations.order_by("updated_at").values_list("id", flat=True)[: min(max(limit, 1), 100)])
    for identity in identities:
        try:
            reconcile_preparation(identity)
        except Exception:
            # A failed provider read must not strand another operation. The
            # durable attempt remains pending for retry; never log its input.
            logger.warning("preparation reconciliation deferred", extra={"operation_id": str(identity)})
    return len(identities)


def reconcile_preparation(operation_id: UUID) -> None:
    """One recoverable dispatch/application step with a current-attempt lease."""
    from engine.models import PreparationAttempt

    needs_cleanup, attempt = _lease_attempt(operation_id)
    if needs_cleanup:
        _start_cleanup(operation_id)
        return
    if attempt is None:
        return
    try:
        task = _task(attempt)
        if attempt.result is not None or attempt.expires_at <= timezone.now():
            if task.interrupt() != TaskInterruptDisposition.TERMINAL_ABSENT:
                return
            _finish_result(attempt)
        elif attempt.dispatched_at is None:
            _dispatch(attempt, task)
        elif task.status() in {"FAILED", "SUCCEEDED"}:
            if task.interrupt() == TaskInterruptDisposition.TERMINAL_ABSENT:
                _apply(attempt, None, "worker-result-missing")
    finally:
        # A lost lease cannot unlock another controller or overwrite its inbox.
        PreparationAttempt.objects.filter(pk=attempt.id, lease_id=attempt.lease_id).update(
            lease_id=None,
            lease_expires_at=None,
        )


def _lease_attempt(operation_id: UUID) -> tuple[bool, PreparationAttempt | None]:
    """Handle lease attempt."""
    from engine.models import PreparationAttempt

    with _locked(operation_id) as operation:
        if operation.current_attempt_id is None:
            return operation.cleanup_pending, None
        attempt = PreparationAttempt.objects.select_for_update().get(pk=operation.current_attempt_id)
        return False, _acquire_attempt_lease(operation, attempt)


def _acquire_attempt_lease(operation: PreparationOperation, attempt: PreparationAttempt) -> PreparationAttempt | None:
    """Acquire an eligible attempt lease while its operation lock is held."""
    now = timezone.now()
    if (attempt.lease_expires_at and attempt.lease_expires_at > now) or attempt.next_dispatch_at > now:
        return None
    try:
        _current_attempt(attempt)
    except (ValueError, ValidationError):
        _fail(operation, "authorization-revoked")
        return None
    attempt.lease_id = uuid4()
    attempt.lease_expires_at = now + timedelta(seconds=_LEASE_SECONDS)
    attempt.save(update_fields=["lease_id", "lease_expires_at"])
    return attempt


def _finish_result(attempt: PreparationAttempt) -> None:
    """Handle finish result."""
    facts, failure = None, ""
    if attempt.expires_at <= timezone.now() and attempt.result is None:
        failure = "deadline-exceeded"
    else:
        try:
            result = validated_result(attempt)
            if result.status == "failed":
                failure = result.failure_code
            else:
                facts = verified_facts(attempt, get_preparation_readback(_grant(attempt)))
        except (ValueError, ValidationError):
            failure = "verification-failed"
    _apply(attempt, facts, failure)


def _dispatch(attempt: PreparationAttempt, task: PreparationTask) -> None:
    """Handle dispatch."""
    reference = task.dispatch(attempt_token(attempt))
    if not reference:
        return
    with _locked(attempt.operation_id) as operation:
        current = _fenced(operation, attempt)
        if current is None:
            return
        current.dispatched_at = timezone.now()
        current.dispatch_count += 1
        current.save(update_fields=["dispatched_at", "dispatch_count"])
        if operation.state == "queued":
            operation.state = "running"
            operation.save(update_fields=["state", "updated_at"])


def _grant(attempt: PreparationAttempt) -> PreparationGrantConfiguration:
    """Handle grant."""
    grant = PreparationGrantConfiguration.model_validate(attempt.input["grant"])
    if grant.digest != attempt.input["grant_digest"]:
        raise ValueError("pinned preparation grant changed")
    return grant


def _task(attempt: PreparationAttempt) -> PreparationTask:
    """Handle task."""
    grant = _grant(attempt)
    if attempt.phase == "cleanup":
        image = grant.cleanup_image
    else:
        image = attempt.input["adapter"]["worker_image" if attempt.phase == "build" else "verifier_image"]
    return get_preparation_task(grant, attempt.phase, image, attempt.operation_id, attempt.id)


def _fenced(operation: PreparationOperation, snapshot: PreparationAttempt) -> PreparationAttempt | None:
    """Handle fenced."""
    from engine.models import PreparationAttempt

    current = PreparationAttempt.objects.select_for_update().get(pk=snapshot.id)
    if (
        operation.current_attempt_id != snapshot.id
        or current.lease_id != snapshot.lease_id
        or current.lease_expires_at is None
        or current.lease_expires_at <= timezone.now()
        or current.input_digest != snapshot.input_digest
        or current.result_digest != snapshot.result_digest
    ):
        return None
    try:
        _current_attempt(current)
    except (ValueError, ValidationError):
        _fail(operation, "authorization-revoked")
        return None
    return current


def _apply(snapshot: PreparationAttempt, facts: VerifiedMaterialization | None, failure: str) -> None:
    """Handle apply."""
    with _locked(snapshot.operation_id) as operation:
        current = _fenced(operation, snapshot)
        if current is None:
            return
        current.disposition = "rejected" if failure else "applied"
        current.save(update_fields=["disposition"])
        if failure:
            if current.phase == "cleanup":
                retry = new_preparation_attempt(operation, "cleanup", evidence=current.input["evidence"])
                retry.next_dispatch_at = timezone.now() + timedelta(seconds=30)
                retry.save(update_fields=["next_dispatch_at"])
            else:
                _fail(operation, failure)
            return
        result = validated_result(current)
        evidence = current.input["evidence"]
        if current.phase == "verify-inputs":
            new_preparation_attempt(
                operation, "build", evidence={"inputs": result.evidence, "input_attempt_id": str(current.id)}
            )
        elif current.phase == "build":
            new_preparation_attempt(
                operation,
                "verify-output",
                evidence={**evidence, "build": result.evidence, "build_attempt_id": str(current.id)},
            )
            operation.state = "verifying"
        elif current.phase == "verify-output":
            if facts is None:
                raise ValueError("verified preparation omitted materialization facts")
            save_admission(operation, facts)
            operation.state = "available"
            operation.current_attempt_id = None
            operation.cleanup_pending = True
        else:
            operation.cleanup_pending = False
            operation.current_attempt_id = None
        operation.save(update_fields=["state", "current_attempt_id", "cleanup_pending", "updated_at"])
        _audit_operation(operation, AuditAction.UPDATE)


def _fail(operation: PreparationOperation, code: str) -> None:
    """Handle fail."""
    operation.state = "failed"
    operation.failure_code = code
    operation.current_attempt_id = None
    operation.cleanup_pending = True
    operation.save(update_fields=["state", "failure_code", "current_attempt_id", "cleanup_pending", "updated_at"])
    _audit_operation(operation, AuditAction.UPDATE)


def _start_cleanup(operation_id: UUID) -> None:
    """Fence all old worker identities before dispatching the operator cleanup image."""
    from engine.models import PreparationAttempt, PreparationOperation, PreparedArtifactAdmission

    operation = PreparationOperation.objects.get(pk=operation_id)
    attempts = list(
        PreparationAttempt.objects.filter(operation=operation).exclude(phase="cleanup").order_by("created_at")
    )
    if len(attempts) > 128:
        raise ValueError("preparation creator history exceeds its bound")
    for attempt in attempts:
        if canonical_payload_digest(attempt.input) != attempt.input_digest:
            raise ValueError("preparation cleanup history changed")
        if _task(attempt).interrupt() != TaskInterruptDisposition.TERMINAL_ABSENT:
            return
    with _locked(operation_id) as current:
        if current.current_attempt_id is not None or not current.cleanup_pending:
            return
        evidence: dict[str, Any] = {"attempts": [str(attempt.id) for attempt in attempts]}
        admission = PreparedArtifactAdmission.objects.filter(operation=current).first()
        if admission:
            if canonical_payload_digest(admission.facts) != admission.facts_digest:
                raise ValueError("preparation admission changed")
            evidence["retained_image"] = {key: admission.facts[key] for key in ("image_ref", "image_id")}
        new_preparation_attempt(current, "cleanup", evidence=evidence)
