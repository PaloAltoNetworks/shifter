"""Scoped authorization commands responsibilities (ADR-066, #2315)."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from shared.audit import RequestAudit
from shared.authorization import (
    AdministrativeRoleChange,
    CredentialCeiling,
    GroupMembershipChange,
    PolicyEffect,
    PolicyRelationshipChange,
    RelationshipSubject,
    RoleAssignmentChange,
    TargetRef,
)
from shared.identity_scope import PrincipalRef, ResourceScope


class AuthorizationMutationConflict(RuntimeError):
    """A different or unresolved mutation owns the serialization fence."""


@dataclass(frozen=True, slots=True)
class PolicyMutationRequest:
    """Validated action-assignment intent with trusted actor and audit context."""

    actor: PrincipalRef
    credential: CredentialCeiling
    subject: RelationshipSubject
    action: str
    target: TargetRef
    scope: ResourceScope
    effect: PolicyEffect
    idempotency_key: str
    model_id: str
    audit: RequestAudit = field(default_factory=RequestAudit)

    def __post_init__(self) -> None:
        PolicyRelationshipChange(self.subject, self.action, self.target, self.effect)
        if not isinstance(self.idempotency_key, str) or not 1 <= len(self.idempotency_key) <= 128:
            raise ValueError("idempotency key must contain 1 to 128 characters")
        if not isinstance(self.model_id, str) or not self.model_id:
            raise ValueError("authorization model id is required")
        if not isinstance(self.audit, RequestAudit):
            raise ValueError("trusted audit attribution is required")


@dataclass(frozen=True, slots=True)
class PolicyMutationResult:
    """Durable operation identity and its current externally visible state."""

    operation_id: UUID
    state: str


type NativeRelationshipChange = GroupMembershipChange | RoleAssignmentChange | AdministrativeRoleChange


@dataclass(frozen=True, slots=True)
class NativeRelationshipMutationRequest:
    """A native group membership or role assignment mutation."""

    actor: PrincipalRef
    credential: CredentialCeiling
    change: NativeRelationshipChange
    scope: ResourceScope
    idempotency_key: str
    model_id: str
    audit: RequestAudit = field(default_factory=RequestAudit)

    def __post_init__(self) -> None:
        if not isinstance(self.change, (GroupMembershipChange, RoleAssignmentChange, AdministrativeRoleChange)):
            raise ValueError("native relationship change is required")
        if not isinstance(self.idempotency_key, str) or not 1 <= len(self.idempotency_key) <= 128:
            raise ValueError("idempotency key must contain 1 to 128 characters")
        if not isinstance(self.model_id, str) or not self.model_id:
            raise ValueError("authorization model id is required")
        if not isinstance(self.audit, RequestAudit):
            raise ValueError("trusted audit attribution is required")


type MutationRequest = PolicyMutationRequest | NativeRelationshipMutationRequest
