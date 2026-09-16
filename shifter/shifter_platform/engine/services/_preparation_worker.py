"""Attempt-scoped private worker input and append-only result inbox access."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.signing import Signer
from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError as ModelValidationError

from shared.artifact_preparation import PreparationWorkerResult
from shared.exceptions import ValidationError
from shared.operation_envelope import canonical_payload_digest

from ._preparation_adapters import _validate_grant, require_preparation_permission, validate_pinned_adapter

if TYPE_CHECKING:
    from engine.models import PreparationAttempt, PreparationOperation

_DENIED = "The preparation worker grant is unavailable"


def attempt_token(attempt: PreparationAttempt) -> str:
    """Mint a deterministic, bounded credential delivered only through a Secret.

    It binds the exact role, immutable input and expiry. The worker has no user
    token or SQL credentials. Key rotation revokes outstanding worker access;
    recovery creates another attempt rather than accepting an unverified token.
    """
    identity = (
        f"{attempt.id}:{attempt.operation_id}:{attempt.phase}:{attempt.input_digest}:{attempt.expires_at.isoformat()}"
    )
    signature = Signer(salt="shifter.artifact-preparation.attempt/v1").signature(identity)
    return f"{attempt.id}.{signature}"


def _authenticate(operation_id: UUID, token: str) -> PreparationAttempt:
    """An opaque ID alone is not authority; unknown/foreign/expired grants agree."""
    from engine.models import PreparationAttempt

    if not isinstance(token, str) or len(token) > 256:
        raise ValidationError(_DENIED)
    try:
        attempt_id = UUID(token.split(".", 1)[0])
    except (ValueError, AttributeError) as exc:
        raise ValidationError(_DENIED) from exc
    attempt = PreparationAttempt.objects.filter(pk=attempt_id, operation_id=operation_id).first()
    if (
        attempt is None
        or attempt.expires_at <= timezone.now()
        or not secrets.compare_digest(attempt_token(attempt), token)
    ):
        raise ValidationError(_DENIED)
    return attempt


def _current_attempt(attempt: PreparationAttempt) -> None:
    """Cancellation, revocation and generation changes revoke ordinary work."""
    operation = attempt.operation
    if operation.current_attempt_id != attempt.id:
        raise ValidationError(_DENIED)
    inherited = {
        key: value
        for key, value in attempt.input.items()
        if key not in {"operation_id", "operation_input_digest", "phase", "evidence"}
    }
    invalid = (
        canonical_payload_digest(operation.input) != operation.input_digest,
        canonical_payload_digest(attempt.input) != attempt.input_digest,
        inherited != operation.input,
        attempt.input.get("operation_id") != str(operation.id),
        attempt.input.get("operation_input_digest") != operation.input_digest,
        attempt.input.get("phase") != attempt.phase,
    )
    if any(invalid):
        raise ValidationError(_DENIED)
    if attempt.phase == "cleanup":
        if not operation.cleanup_pending:
            raise ValidationError(_DENIED)
    else:
        _validate_active_authority(operation)


def _validate_active_authority(operation: PreparationOperation) -> None:
    """Handle validate active authority."""
    if operation.state in {"cancelled", "failed", "available"} or not operation.adapter.grant.active:
        raise ValidationError(_DENIED)
    require_preparation_permission(operation.requested_by, "prepare_artifacts")
    adapter = operation.adapter
    manifest = validate_pinned_adapter(adapter)
    configuration = _validate_grant(adapter.grant, manifest)
    if operation.input["grant_digest"] != configuration.digest or operation.input["manifest_digest"] != manifest.digest:
        raise ValidationError(_DENIED)


def read_preparation_worker_input(operation_id: UUID, token: str) -> dict[str, Any]:
    """Read one authenticated immutable input; no registry or inventory access."""
    attempt = _authenticate(operation_id, token)
    _current_attempt(attempt)
    return {"attempt_id": str(attempt.id), "input_digest": attempt.input_digest, "input": attempt.input}


def record_preparation_worker_result(operation_id: UUID, token: str, payload: object) -> str:
    """Record a receipt, with role/generation/replay fences; never admit output."""
    from engine.models import PreparationAttempt, PreparationOperation

    authenticated = _authenticate(operation_id, token)
    try:
        result = PreparationWorkerResult.model_validate(payload)
    except ModelValidationError as exc:
        raise ValidationError("The preparation worker result is invalid") from exc
    if (
        result.operation_id != operation_id
        or result.attempt_id != authenticated.id
        or result.phase != authenticated.phase
        or result.input_digest != authenticated.input_digest
    ):
        raise ValidationError("The preparation result does not match its worker grant")
    normalized = result.model_dump(mode="json")
    digest = canonical_payload_digest(normalized)
    with transaction.atomic():
        # Match the applier's operation-before-attempt order. Cancellation locks
        # this same operation row, so a stale worker cannot race authoritative state.
        PreparationOperation.objects.select_for_update().get(pk=operation_id)
        attempt = PreparationAttempt.objects.select_for_update().get(pk=authenticated.id)
        if attempt.result_digest:
            if attempt.result_digest != digest:
                raise ValidationError("The preparation worker result conflicts with its recorded receipt")
            return "received"
        _current_attempt(attempt)
        if attempt.expires_at <= timezone.now():
            raise ValidationError(_DENIED)
        attempt.result = normalized
        attempt.result_digest = digest
        attempt.disposition = "received"
        attempt.save(update_fields=["result", "result_digest", "disposition"])
        return "received"
