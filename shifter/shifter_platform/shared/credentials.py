"""Provider-neutral authenticated identity and immutable credential limits."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from shared.authorization import CredentialCeiling, TargetRef
from shared.identity_scope import PrincipalRef, ResourceScope


def _validate_credential_shape(context: CredentialContext) -> None:
    """Validate provider-neutral identity, ceiling, proof ID, and scope shapes."""
    if not isinstance(context.principal, PrincipalRef) or not isinstance(context.ceiling, CredentialCeiling):
        raise ValueError("Invalid credential context")
    expected_kind = {"session": "human", "personal": "human", "temporary": "human", "service": "service"}
    if expected_kind.get(context.kind) != context.principal.kind:
        raise ValueError("Credential and principal kinds disagree")
    if not isinstance(context.credential_uuid, UUID) or not context.credential_uuid.int:
        raise ValueError("Invalid credential identity")
    if not isinstance(context.scopes, frozenset) or any(not isinstance(scope, str) for scope in context.scopes):
        raise ValueError("Credential scopes must be immutable")


def _validate_event_binding(context: CredentialContext) -> None:
    """Require exact event binding only for temporary participant proofs."""
    if context.kind != "temporary":
        if context.event_uuid is not None:
            raise ValueError("Only temporary credentials fix an authentication event")
        return
    if not isinstance(context.event_uuid, UUID) or not context.event_uuid.int:
        raise ValueError("Temporary credentials require an explicit event")
    if not context.ceiling.actions <= {"event.read", "event.participate"}:
        raise ValueError("Temporary credential cannot leave event scope")
    if context.ceiling.target != TargetRef("event", context.event_uuid):
        raise ValueError("Temporary credential ceiling must match its event")


@dataclass(frozen=True, slots=True)
class CredentialContext:
    """Admission evidence; application policy and domain lifecycle still apply."""

    principal: PrincipalRef
    kind: Literal["session", "personal", "service", "temporary"]
    credential_uuid: UUID
    ceiling: CredentialCeiling
    scopes: frozenset[str]
    event_uuid: UUID | None = None

    def __post_init__(self) -> None:
        _validate_credential_shape(self)
        _validate_event_binding(self)


_service_verifier: Callable[[str], CredentialContext] | None = None

_temporary_resolver: Callable[[object], CredentialContext] | None = None


def bind_temporary_credential_resolver(resolver: Callable[[object], CredentialContext]) -> None:
    """Compose the owning CTF lifecycle resolver without importing it in shared."""
    global _temporary_resolver
    if _temporary_resolver is not None and _temporary_resolver is not resolver:
        raise ValueError("Temporary credential resolver already bound")
    _temporary_resolver = resolver


def temporary_credential(user: object) -> CredentialContext:
    """Resolve a temporary user's one live participant event, or deny."""
    if _temporary_resolver is None:
        raise ValueError("Temporary credential unavailable")
    return _temporary_resolver(user)


def bind_service_credential_verifier(verifier: Callable[[str], CredentialContext]) -> None:
    """Bind the sole config-owned native GCP verifier during composition."""
    global _service_verifier
    if _service_verifier is not None and _service_verifier is not verifier:
        raise ValueError("A service credential verifier is already bound")
    _service_verifier = verifier


def verify_service_credential(raw_token: str) -> CredentialContext:
    """Use the native verifier without importing a provider into shared."""
    if _service_verifier is None:
        raise ValueError("Service credential verification unavailable")
    return _service_verifier(raw_token)


_scope_resolver: Callable[[TargetRef], ResourceScope] | None = None


def bind_credential_scope_resolver(resolver: Callable[[TargetRef], ResourceScope]) -> None:
    """Bind config's concrete cross-domain target ancestry composition."""
    global _scope_resolver
    if _scope_resolver is not None and _scope_resolver is not resolver:
        raise ValueError("A credential scope resolver is already bound")
    _scope_resolver = resolver


def resolve_credential_scope(target: TargetRef) -> ResourceScope:
    """Require SQL-owned ancestry; absent customer identity never means installation."""
    if target == TargetRef("installation"):
        return ResourceScope("installation")
    if _scope_resolver is None:
        raise ValueError("Credential target scope unavailable")
    return _scope_resolver(target)
