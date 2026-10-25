"""Scoped authorization journal responsibilities (ADR-066, #2315)."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from shared.authorization import (
    AdministrativeRoleChange,
    AuthorizationProvider,
    GroupMembershipChange,
    PolicyEffect,
    PolicyRelationshipChange,
    RelationshipSubject,
    RoleAssignmentChange,
    TargetRef,
    VersionedRelationshipChange,
)
from shared.authorization.catalog import TargetType
from shared.authorization.relationships import SubjectKind
from shared.identity_scope import ResourceScope
from workspaces.models import (
    AuthorizationMutationFence,
    AuthorizationOperation,
)

from ._authorization_commands import (
    AuthorizationMutationConflict,
    MutationRequest,
    NativeRelationshipChange,
    PolicyMutationRequest,
    PolicyMutationResult,
)

_RECONCILE_LEASE = timedelta(seconds=30)


def _hash(payload: object) -> str:
    """Digest canonical JSON for stable mutation and fence identities."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _scope_payload(scope: ResourceScope) -> dict[str, object]:
    """Serialize trusted ancestry without importing persistence identifiers."""
    return {
        "kind": scope.kind,
        "account": str(scope.account_uuid) if scope.account_uuid else None,
        "organization": str(scope.organization_uuid) if scope.organization_uuid else None,
        "workspace": str(scope.workspace_uuid) if scope.workspace_uuid else None,
    }


def _credential_target_payload(request: MutationRequest) -> dict[str, object]:
    """Bind journals to target-limited proof without changing unbounded request identities."""
    target = request.credential.target
    if target is None:
        return {}
    return {"credential_target_kind": target.type, "credential_target": str(target.uuid) if target.uuid else None}


def _request_payload(request: MutationRequest) -> dict[str, object]:
    """Capture every authorization-relevant field for idempotency comparison."""
    common = {
        "actor": str(request.actor.uuid),
        "actor_kind": request.actor.kind,
        "scope": _scope_payload(request.scope),
        "model_id": request.model_id,
        "credential_actions": sorted(request.credential.actions),
        **_credential_target_payload(request),
    }
    if isinstance(request, PolicyMutationRequest):
        return {
            **common,
            "relationship_kind": AuthorizationOperation.RelationshipKind.ACTION,
            "subject_kind": request.subject.kind,
            "subject": str(request.subject.uuid),
            "action": request.action,
            "target_kind": request.target.type,
            "target": str(request.target.uuid) if request.target.uuid else None,
            "effect": request.effect.value,
        }
    return {**common, **_native_payload(request.change)}


def _native_payload(change: NativeRelationshipChange) -> dict[str, object]:
    """Serialize native relationship identities for stable idempotency digests."""
    if isinstance(change, GroupMembershipChange):
        return {
            "relationship_kind": AuthorizationOperation.RelationshipKind.GROUP_MEMBERSHIP,
            "subject_kind": "principal",
            "subject": str(change.principal_uuid),
            "action": "",
            "target_kind": "group",
            "target": str(change.group_uuid),
            "effect": change.effect.value,
        }
    if isinstance(change, AdministrativeRoleChange):
        return {
            "relationship_kind": AuthorizationOperation.RelationshipKind.PREDEFINED_ROLE,
            "subject_kind": change.subject.kind,
            "subject": str(change.subject.uuid),
            "action": change.policy_code,
            "target_kind": change.target.type,
            "target": str(change.target.uuid) if change.target.uuid else None,
            "effect": change.effect.value,
        }
    return {
        "relationship_kind": AuthorizationOperation.RelationshipKind.ROLE_ASSIGNMENT,
        "subject_kind": change.subject.kind,
        "subject": str(change.subject.uuid),
        "action": "",
        "target_kind": "role",
        "target": str(change.role_uuid),
        "effect": change.effect.value,
    }


def _idempotency_namespace(request: MutationRequest) -> str:
    """Isolate idempotency keys by authenticated actor and exact scope."""
    return _hash(
        {
            "actor": str(request.actor.uuid),
            "actor_kind": request.actor.kind,
            "scope": _scope_payload(request.scope),
        }
    )


def _request_change(request: MutationRequest) -> PolicyRelationshipChange | NativeRelationshipChange:
    """Normalize action and native requests to their typed relationship changes."""
    if isinstance(request, PolicyMutationRequest):
        return PolicyRelationshipChange(request.subject, request.action, request.target, request.effect)
    return request.change


def _fence_key(request: MutationRequest) -> str:
    """Serialize all generations affecting the same positive relationship."""
    change = _request_change(request)
    grant = change.grant_tuple
    return _hash({"user": grant.user, "relation": grant.relation, "object": grant.object})


def _operation_fields(request: MutationRequest) -> dict[str, object]:
    """Map validated request intent into durable operation columns."""
    payload = _request_payload(request)
    return {
        "relationship_kind": payload["relationship_kind"],
        "subject_kind": payload["subject_kind"],
        "subject_uuid": payload["subject"],
        "action": payload["action"],
        "effect": payload["effect"],
        "target_kind": payload["target_kind"],
        "target_uuid": payload["target"],
    }


def _audit(operation: AuthorizationOperation, action: str, reason: str) -> None:
    """Write a strict operation audit without disclosing provider payloads."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.AUTHORIZATION_OPERATION,
            entity_id=0,
            entity_ref=str(operation.id),
            action=action,
            actor_type=operation.audit_actor_type or "system",
            actor_id=operation.audit_actor_id,
            actor_principal_uuid=operation.audit_actor_principal_uuid,
            new_state={
                "action": operation.action,
                "effect": operation.effect,
                "state": operation.state,
                "reason": reason,
                "target_kind": operation.target_kind,
            },
            context="authorization_policy",
            source_ip=operation.audit_source_ip,
            user_agent=operation.audit_user_agent,
            request_id=operation.audit_request_id,
        ),
        strict=True,
    )


def _operation_result(operation: AuthorizationOperation) -> PolicyMutationResult:
    """Expose only the durable operation identity and current state."""
    return PolicyMutationResult(operation.id, operation.state)


def _reserve(
    request: MutationRequest,
    provider: AuthorizationProvider,
    *,
    state: AuthorizationOperation.State,
    reason: str,
    block: bool,
) -> tuple[AuthorizationOperation, bool]:
    """Atomically reserve an idempotency key and optionally fence the relationship."""
    digest = _hash(_request_payload(request))
    idempotency_namespace = _idempotency_namespace(request)
    fence_key = _fence_key(request)
    with transaction.atomic():
        AuthorizationMutationFence.objects.get_or_create(key=fence_key)
        fence = AuthorizationMutationFence.objects.select_for_update().get(key=fence_key)
        existing = AuthorizationOperation.objects.filter(
            idempotency_namespace=idempotency_namespace,
            idempotency_key=request.idempotency_key,
        ).first()
        if existing is not None:
            if existing.request_digest != digest:
                raise AuthorizationMutationConflict("idempotency key is bound to a different mutation")
            _assert_operation_provider(existing, provider)
            return existing, False
        if fence.blocked_operation_id is not None:
            raise AuthorizationMutationConflict("an unresolved authorization mutation blocks this edit")
        if block:
            fence.generation += 1
        operation_fields = _operation_fields(request)
        try:
            with transaction.atomic():
                operation = AuthorizationOperation.objects.create(
                    idempotency_key=request.idempotency_key,
                    idempotency_namespace=idempotency_namespace,
                    request_digest=digest,
                    fence_key=fence_key,
                    generation=fence.generation,
                    state=state,
                    actor_uuid=request.actor.uuid,
                    actor_kind=request.actor.kind,
                    audit_actor_type=request.audit.actor_type,
                    audit_actor_id=request.audit.actor_id,
                    audit_actor_principal_uuid=request.audit.actor_principal_uuid,
                    audit_source_ip=request.audit.source_ip,
                    audit_user_agent=request.audit.user_agent,
                    audit_request_id=request.audit.request_id,
                    **operation_fields,
                    scope_kind=request.scope.kind,
                    account_uuid=request.scope.account_uuid,
                    organization_uuid=request.scope.organization_uuid,
                    workspace_uuid=request.scope.workspace_uuid,
                    model_id=request.model_id,
                    provider_store_id=provider.store_id,
                    credential_digest=_hash(
                        {
                            "actions": sorted(request.credential.actions),
                            "actor_type": request.audit.actor_type,
                            "actor_id": request.audit.actor_id,
                            **(
                                {"actor_principal_uuid": str(request.audit.actor_principal_uuid)}
                                if request.audit.actor_principal_uuid
                                else {}
                            ),
                            **_credential_target_payload(request),
                        }
                    ),
                    outcome_reason=reason,
                    reconcile_lease_until=timezone.now() + _RECONCILE_LEASE if block else None,
                )
        except IntegrityError as exc:
            winner = AuthorizationOperation.objects.filter(
                idempotency_namespace=idempotency_namespace,
                idempotency_key=request.idempotency_key,
            ).first()
            if winner is None:
                raise
            if winner.request_digest != digest:
                raise AuthorizationMutationConflict("idempotency key is bound to a different mutation") from exc
            _assert_operation_provider(winner, provider)
            return winner, False
        if block:
            fence.blocked_operation_id = operation.id
        fence.save(update_fields=["generation", "blocked_operation_id", "updated_at"])
        audit_action = {
            AuthorizationOperation.State.REQUESTED: AuditAction.AUTHORIZATION_REQUESTED,
            AuthorizationOperation.State.DENIED: AuditAction.AUTHORIZATION_DENIED,
        }[state]
        _audit(operation, audit_action, reason)
        return operation, True


def _set_outcome(
    owner: AuthorizationOperation, state: AuthorizationOperation.State, reason: str
) -> AuthorizationOperation:
    """Persist a lease-owned outcome and release only terminal operation fences."""
    with transaction.atomic():
        operation = AuthorizationOperation.objects.select_for_update().get(pk=owner.id)
        if operation.state in {AuthorizationOperation.State.CONFIRMED, AuthorizationOperation.State.DENIED}:
            return operation
        if operation.reconcile_lease_until != owner.reconcile_lease_until:
            return operation
        operation.state = state
        operation.outcome_reason = reason
        operation.reconcile_lease_until = None
        operation.save(update_fields=["state", "outcome_reason", "reconcile_lease_until", "updated_at"])
        fence = AuthorizationMutationFence.objects.select_for_update().get(key=operation.fence_key)
        if (
            state in {AuthorizationOperation.State.CONFIRMED, AuthorizationOperation.State.DENIED}
            and fence.blocked_operation_id == operation.id
        ):
            fence.blocked_operation_id = None
            fence.save(update_fields=["blocked_operation_id", "updated_at"])
        audit_action = {
            AuthorizationOperation.State.CONFIRMED: AuditAction.AUTHORIZATION_CONFIRMED,
            AuthorizationOperation.State.DENIED: AuditAction.AUTHORIZATION_DENIED,
            AuthorizationOperation.State.UNRESOLVED: AuditAction.AUTHORIZATION_UNRESOLVED,
        }[state]
        _audit(operation, audit_action, reason)
        return operation


def _clear_reconcile_lease(owner: AuthorizationOperation) -> AuthorizationOperation:
    """Release the caller's recovery lease without clearing the mutation fence."""
    with transaction.atomic():
        operation = AuthorizationOperation.objects.select_for_update().get(pk=owner.id)
        if operation.reconcile_lease_until != owner.reconcile_lease_until:
            return operation
        operation.reconcile_lease_until = None
        operation.save(update_fields=["reconcile_lease_until", "updated_at"])
        return operation


def _base_change_from_operation(
    operation: AuthorizationOperation,
) -> PolicyRelationshipChange | NativeRelationshipChange:
    """Reconstruct and validate the typed relationship from durable intent."""
    effect = PolicyEffect(operation.effect)
    subject_uuid = UUID(str(operation.subject_uuid))
    target_uuid = UUID(str(operation.target_uuid)) if operation.target_uuid is not None else None
    if operation.relationship_kind == AuthorizationOperation.RelationshipKind.GROUP_MEMBERSHIP:
        if target_uuid is None:
            raise AuthorizationMutationConflict("authorization operation is invalid")
        return GroupMembershipChange(target_uuid, subject_uuid, effect)
    if operation.relationship_kind == AuthorizationOperation.RelationshipKind.ROLE_ASSIGNMENT:
        if target_uuid is None:
            raise AuthorizationMutationConflict("authorization operation is invalid")
        return RoleAssignmentChange(
            target_uuid,
            RelationshipSubject(cast(SubjectKind, operation.subject_kind), subject_uuid),
            effect,
        )
    change_type = (
        AdministrativeRoleChange
        if operation.relationship_kind == AuthorizationOperation.RelationshipKind.PREDEFINED_ROLE
        else PolicyRelationshipChange
    )
    return change_type(
        RelationshipSubject(cast(SubjectKind, operation.subject_kind), subject_uuid),
        operation.action,
        TargetRef(cast(TargetType, operation.target_kind), target_uuid),
        effect,
    )


def _change_from_operation(operation: AuthorizationOperation) -> VersionedRelationshipChange:
    """Bind reconstructed intent to its append-only fence generation."""
    return VersionedRelationshipChange(
        _base_change_from_operation(operation),
        operation.fence_key,
        operation.generation,
    )


def _assert_request_provider(request: MutationRequest, provider: AuthorizationProvider) -> None:
    """Require the requested immutable model and an identified provider store."""
    if not provider.store_id or provider.model_id != request.model_id:
        raise AuthorizationMutationConflict("authorization provider binding changed")


def _assert_operation_provider(operation: AuthorizationOperation, provider: AuthorizationProvider) -> None:
    """Reject recovery or retry against a different store or model."""
    if not operation.provider_store_id or (
        operation.provider_store_id != provider.store_id or operation.model_id != provider.model_id
    ):
        raise AuthorizationMutationConflict("authorization provider binding changed")
