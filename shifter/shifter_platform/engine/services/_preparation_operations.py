"""Explicit preparation requests, immutable attempts and cancellation fences."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from pydantic import ValidationError as ModelValidationError

from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, RequestAudit, audit_log
from shared.exceptions import ValidationError
from shared.operation_envelope import canonical_payload_digest
from shared.raes.preparation_contract import PreparationPackage, select_preparation
from shared.raes.preparation_inputs import require_input_trust

from ._preparation_adapters import (
    _locked_grant,
    _validate_grant,
    require_preparation_permission,
    validate_pinned_adapter,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from engine.models import PreparationAttempt, PreparationOperation


@dataclass(frozen=True)
class PreparationView:
    """Bounded operator status; no private recipe, registry or provider payload."""

    id: UUID | None
    state: str
    failure_code: str
    cleanup_pending: bool = False
    reused: bool = False


def request_artifact_preparation(
    user: User, adapter_id: UUID, package_input: object, *, audit: RequestAudit | None = None
) -> PreparationView:
    """Enqueue preparation after the CMS validates a registered immutable package.

    Idempotency binds package/requirement, manifest, scope and cloud policy. A
    retry never changes an existing operation's inputs or executable identity.
    """
    from engine.models import PreparationAdapter, PreparationOperation, PreparationScopeLock

    require_preparation_permission(user, "prepare_artifacts")
    try:
        package = PreparationPackage.model_validate(package_input)
    except ModelValidationError as exc:
        raise ValidationError("The preparation package projection is invalid") from exc
    if len(package.input_bindings) != 1:
        raise ValidationError("The contained GCE preparation adapter requires exactly one input binding")
    if _has_admitted_availability(package):
        # Availability belongs to the tenant inventory; another operator's
        # private preparation history never becomes this requester's status URL.
        return PreparationView(None, "available", "", reused=True)
    with transaction.atomic():
        initial = PreparationAdapter.objects.filter(pk=adapter_id).first()
        if initial is None:
            raise ValidationError("The preparation adapter is unavailable")
        # Stable scope precedes grant/adapter/operation locks. Another grant
        # version cannot acquire a separate budget for the same worker scope.
        PreparationScopeLock.objects.get_or_create(scope_digest=initial.scope_digest)
        PreparationScopeLock.objects.select_for_update().get(pk=initial.scope_digest)
        grant = _locked_grant(initial.grant_id)
        adapter = PreparationAdapter.objects.select_for_update().get(pk=adapter_id)
        manifest = validate_pinned_adapter(adapter)
        configuration = _validate_grant(grant, manifest)
        select_preparation(package.requirement, manifest, package.specification_id)
        try:
            require_input_trust(
                package.input_bindings, package.requirement.locked_inputs, configuration.trusted_input_bindings
            )
        except ValueError as exc:
            raise ValidationError("The preparation inputs lack valid material or operator admission") from exc
        payload = {
            "protocol": manifest.protocol,
            "scope_digest": grant.scope_digest,
            "grant_digest": grant.configuration_digest,
            "grant": grant.configuration,
            "manifest_digest": adapter.manifest_digest,
            "adapter": adapter.manifest,
            "package": package.model_dump(mode="json"),
        }
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > 96 * 1024:
            raise ValidationError("The combined preparation input exceeds the worker message size limit")
        digest = canonical_payload_digest(payload)
        existing = PreparationOperation.objects.filter(input_digest=digest).first()
        if existing is not None:
            _authorize_operation(user, existing)
            return _view(existing)
        if adapter.state != PreparationAdapter.State.ENABLED:
            raise ValidationError("The preparation adapter cannot start new operations")
        _ensure_capacity(grant.scope_digest, configuration.max_concurrent_operations)
        row = PreparationOperation.objects.create(
            adapter=adapter,
            requested_by=user,
            scope_digest=grant.scope_digest,
            input_digest=digest,
            input=payload,
        )
        # Verify actual locked inputs with the independent verifier before any
        # builder receives execution authority. This is not a declared-lock test.
        new_preparation_attempt(row, "verify-inputs")
        _audit_operation(row, AuditAction.CREATE, user=user, audit=audit)
        return _view(row)


def _has_admitted_availability(package: PreparationPackage) -> bool:
    """Use the ordinary launch resolver; an inventory miss never starts work here."""
    from shared.raes.artifact_inventory import build_artifact_supply
    from shared.raes.artifact_resolution import ArtifactResolutionStatus, resolve_artifact_requirement
    from shared.raes.manifest import shifter_artifact_mechanism_capabilities, shifter_backend_apparatus

    from ._raes_image import list_backend_artifacts

    inventory = list_backend_artifacts(provider="gce")
    supply = build_artifact_supply(
        {package.requirement_address: package.requirement},
        inventory,
        capabilities=shifter_artifact_mechanism_capabilities(),
    )
    result = resolve_artifact_requirement(
        package.requirement,
        address=package.requirement_address,
        capabilities=supply.capabilities,
        availability=supply.availability.get(package.requirement_address),
        backend=shifter_backend_apparatus(),
        prepared_materializations=supply.materializations,
    )
    return result.status is ArtifactResolutionStatus.SATISFIED


def _ensure_capacity(scope_digest: str, limit: int) -> None:
    """Caller holds the stable scope mutex across all grant versions."""
    from engine.models import PreparationOperation

    occupied = (
        PreparationOperation.objects.filter(scope_digest=scope_digest)
        .filter(Q(state__in=["queued", "running", "verifying"]) | Q(cleanup_pending=True))
        .count()
    )
    if occupied >= limit:
        raise ValidationError("Artifact preparation capacity is occupied")


def retry_artifact_preparation(user: User, operation_id: UUID, *, audit: RequestAudit | None = None) -> PreparationView:
    """Explicitly retry cleaned terminal work with a fresh authenticated attempt."""
    from engine.models import PreparationAdapter, PreparationOperation, PreparationScopeLock

    require_preparation_permission(user, "prepare_artifacts")
    with transaction.atomic():
        initial = PreparationOperation.objects.select_related("adapter").filter(pk=operation_id).first()
        initial = _authorize_operation(user, initial)
        PreparationScopeLock.objects.select_for_update().get(pk=initial.scope_digest)
        grant = _locked_grant(initial.adapter.grant_id)
        adapter = PreparationAdapter.objects.select_for_update().get(pk=initial.adapter_id)
        row = PreparationOperation.objects.select_for_update().get(pk=operation_id)
        row = _authorize_operation(user, row)
        if row.state in {"queued", "running", "verifying", "available"}:
            return _view(row)
        manifest = validate_pinned_adapter(adapter)
        configuration = _validate_grant(grant, manifest)
        if (
            row.cleanup_pending
            or adapter.state != PreparationAdapter.State.ENABLED
            or canonical_payload_digest(row.input) != row.input_digest
            or row.input["grant_digest"] != configuration.digest
            or row.input["manifest_digest"] != manifest.digest
        ):
            raise ValidationError("The artifact preparation cannot be retried before cleanup and current authorization")
        _ensure_capacity(row.scope_digest, configuration.max_concurrent_operations)
        from engine.models import PreparationAttempt

        if PreparationAttempt.objects.filter(operation=row).exclude(phase="cleanup").count() > 93:
            raise ValidationError("The artifact preparation retry limit has been reached")
        row.state = "queued"
        row.failure_code = ""
        row.save(update_fields=["state", "failure_code", "updated_at"])
        new_preparation_attempt(row, "verify-inputs")
        _audit_operation(row, AuditAction.RESUME, user=user, audit=audit)
        return _view(row)


def new_preparation_attempt(
    operation: PreparationOperation, phase: str, *, evidence: dict[str, Any] | None = None
) -> PreparationAttempt:
    """Create one input/inbox identity inside the caller's operation transaction."""
    from engine.models import PreparationAttempt

    now = timezone.now()
    payload = {
        **operation.input,
        "operation_id": str(operation.id),
        "operation_input_digest": operation.input_digest,
        "phase": phase,
        "evidence": evidence or {},
    }
    attempt = PreparationAttempt.objects.create(
        operation=operation,
        phase=phase,
        input=payload,
        input_digest=canonical_payload_digest(payload),
        expires_at=now + timedelta(seconds=operation.input["grant"].get("max_duration_seconds", 3600)),
        next_dispatch_at=now,
    )
    operation.current_attempt_id = attempt.id
    operation.save(update_fields=["current_attempt_id", "updated_at"])
    return attempt


def cancel_artifact_preparation(
    user: User, operation_id: UUID, *, audit: RequestAudit | None = None
) -> PreparationView:
    """Fence admission first; cleanup is independently retried by the controller."""
    from engine.models import PreparationOperation

    require_preparation_permission(user, "prepare_artifacts")
    with transaction.atomic():
        row = PreparationOperation.objects.select_for_update().filter(pk=operation_id).first()
        row = _authorize_operation(user, row)
        if row.state not in {"available", "failed", "cancelled"}:
            row.state = "cancelled"
            row.current_attempt_id = None
            row.cleanup_pending = True
            row.save(update_fields=["state", "current_attempt_id", "cleanup_pending", "updated_at"])
            _audit_operation(row, AuditAction.CANCEL, user=user, audit=audit)
        return _view(row)


def get_artifact_preparation(user: User, operation_id: UUID) -> PreparationView:
    """Scope private progress to the requester or explicit adapter administrator."""
    from engine.models import PreparationOperation

    require_preparation_permission(user, "prepare_artifacts")
    row = PreparationOperation.objects.filter(pk=operation_id).first()
    row = _authorize_operation(user, row)
    return _view(row)


def _authorize_operation(user: User, row: PreparationOperation | None) -> PreparationOperation:
    """Foreign and missing operation identities have the same bounded failure."""
    if row is None or (row.requested_by_id != user.id and not user.has_perm("engine.manage_preparation_adapters")):
        raise ValidationError("The artifact preparation is unavailable")
    return row


def _audit_operation(
    row: PreparationOperation, action: str, *, user: User | None = None, audit: RequestAudit | None = None
) -> None:
    """Successful mutation and bounded audit commit together, or both roll back."""
    attribution = audit or RequestAudit()
    default_actor = AuditActorType.USER if user is not None else AuditActorType.SYSTEM
    actor_id = attribution.actor_id
    if attribution.actor_type is None and user is not None:
        actor_id = user.id
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.ARTIFACT_PREPARATION,
            entity_id=0,
            action=action,
            actor_type=attribution.actor_type or default_actor,
            actor_id=actor_id,
            request_id=attribution.request_id or str(row.id),
            source_ip=attribution.source_ip,
            user_agent=attribution.user_agent,
            new_state={"id": str(row.id), "state": row.state, "input_digest": row.input_digest},
        ),
        strict=True,
    )


def _view(row: PreparationOperation) -> PreparationView:
    """Keep operational evidence and ORM state behind the owning engine service."""
    return PreparationView(row.id, row.state, row.failure_code, row.cleanup_pending)
