"""Dependency-neutral authorization request and decision contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from shared.identity_scope import PrincipalRef, ResourceScope

from .catalog import AuthorizationContractError, TargetType, action_definition


def _valid_uuid(value: object) -> bool:
    """Accept only nonzero UUID instances as public object identities."""
    return isinstance(value, UUID) and value.int != 0


@dataclass(frozen=True, slots=True)
class TargetRef:
    """Stable public identity of the object an action targets."""

    type: TargetType
    uuid: UUID | None = None

    def __post_init__(self) -> None:
        if self.type == "installation":
            if self.uuid is not None:
                raise AuthorizationContractError("Installation target cannot have an object identity")
            return
        if self.type not in {"account", "organization", "workspace", "event", "range"} or not _valid_uuid(self.uuid):
            raise AuthorizationContractError("Invalid authorization target")


@dataclass(frozen=True, slots=True)
class CredentialCeiling:
    """Server-derived exact action ceiling for the admitted credential."""

    actions: frozenset[str]
    target: TargetRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.actions, frozenset):
            raise AuthorizationContractError("Credential ceiling must be immutable")
        if self.target is not None and not isinstance(self.target, TargetRef):
            raise AuthorizationContractError("Credential target must be an exact target reference")
        for action in self.actions:
            action_definition(action)

    def permits(self, action: str, target: TargetRef | None = None) -> bool:
        return action in self.actions and (self.target is None or self.target == target)


def _validate_target_scope(target: TargetRef, scope: ResourceScope) -> None:
    """Reject targets that disagree with the server-resolved ancestry."""
    if target.type == "installation":
        if scope.kind != "installation":
            raise AuthorizationContractError("Installation target requires installation scope")
        return
    if scope.kind != "account":
        raise AuthorizationContractError("Customer target requires account scope")
    expected = {
        "account": scope.account_uuid,
        "organization": scope.organization_uuid,
        "workspace": scope.workspace_uuid,
    }.get(target.type)
    if target.type in {"account", "organization", "workspace"} and target.uuid != expected:
        raise AuthorizationContractError("Authorization target does not match resolved scope")


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """One validated application authorization check."""

    principal: PrincipalRef
    action: str
    target: TargetRef
    scope: ResourceScope
    credential: CredentialCeiling

    def __post_init__(self) -> None:
        if not isinstance(self.principal, PrincipalRef) or not isinstance(self.scope, ResourceScope):
            raise AuthorizationContractError("Invalid principal or scope")
        definition = action_definition(self.action)
        if definition.target_type != self.target.type:
            raise AuthorizationContractError("Action target type does not match target")
        _validate_target_scope(self.target, self.scope)
        if not self.credential.permits(self.action, self.target):
            raise AuthorizationContractError("Action exceeds credential ceiling")


class DecisionKind(StrEnum):
    """Closed authorization outcomes, including fail-closed evaluator failures."""

    ALLOWED = "allowed"
    DENIED = "denied"
    EVALUATOR_ERROR = "evaluator_error"


_REASONS = frozenset(
    {
        "policy_allowed",
        "policy_denied",
        "credential_denied",
        "invalid_request",
        "evaluator_unavailable",
        "incomplete_batch",
    }
)


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Bounded result that never carries provider data or exception text."""

    kind: DecisionKind
    reason: str

    def __post_init__(self) -> None:
        if self.reason not in _REASONS:
            raise AuthorizationContractError("Unknown authorization decision reason")

    @property
    def allowed(self) -> bool:
        return self.kind == DecisionKind.ALLOWED
