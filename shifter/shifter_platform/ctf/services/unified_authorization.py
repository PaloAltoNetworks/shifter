"""CTF-owned composition of live principal, event scope and shared policy."""

from __future__ import annotations

from uuid import UUID

from ctf.exceptions import CTFError, CTFPermissionError
from ctf.services.credential_scope import event_credential_scope
from shared.authorization import (
    AuthorizationContractError,
    AuthorizationRequest,
    DecisionKind,
    TargetRef,
    configured_authorization_provider,
)
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from shared.principal_port import PrincipalResolutionError, resolve_principal
from workspaces.services import event_placement_scope

_DENIED = "CTF authority denied"
_UNAVAILABLE = "CTF authority unavailable"


def require_event_action(credential: CredentialContext, event_uuid: UUID, action: str) -> None:
    """Require a live exact event decision; creator and CTF staff imply nothing."""
    if credential.kind == "temporary":
        raise CTFPermissionError(_DENIED)
    try:
        principal = resolve_principal(credential.principal)
        request = AuthorizationRequest(
            principal,
            action,
            TargetRef("event", event_uuid),
            event_credential_scope(event_uuid),
            credential.ceiling,
        )
    except (ValueError, PrincipalResolutionError, AuthorizationContractError) as exc:
        raise CTFPermissionError(_DENIED) from exc
    _require_policy(request)


def require_event_creation(credential: CredentialContext, parent: TargetRef) -> ResourceScope:
    """Authorize creation at an existing customer parent, then return its SQL scope."""
    if (
        credential.kind == "temporary"
        or parent.type not in {"account", "organization", "workspace"}
        or parent.uuid is None
    ):
        raise CTFPermissionError(_DENIED)
    try:
        principal = resolve_principal(credential.principal)
        scope = event_placement_scope(parent.type, parent.uuid)
        request = AuthorizationRequest(
            principal,
            f"{parent.type}.create_event",
            parent,
            scope,
            credential.ceiling,
        )
    except (ValueError, PrincipalResolutionError, AuthorizationContractError) as exc:
        raise CTFPermissionError(_DENIED) from exc
    _require_policy(request)
    return scope


def _require_policy(request: AuthorizationRequest) -> None:
    """Keep evaluator failures distinct from an explicit policy denial."""
    try:
        decision = configured_authorization_provider().check(request)
    except Exception:
        raise CTFError(_UNAVAILABLE, code="CTF_AUTHORITY_UNAVAILABLE") from None
    if decision.kind == DecisionKind.EVALUATOR_ERROR:
        raise CTFError(_UNAVAILABLE, code="CTF_AUTHORITY_UNAVAILABLE")
    if not decision.allowed:
        raise CTFPermissionError(_DENIED)
