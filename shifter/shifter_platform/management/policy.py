"""Installation principal-administration policy seam for management services."""

from __future__ import annotations

from shared.authorization import AuthorizationProvider, AuthorizationRequest, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from shared.principal_port import resolve_principal

_DENIED = "Principal administration denied"


def require_principal_administration(actor: CredentialContext, provider: AuthorizationProvider | None) -> None:
    """Check the live installation action before any identity read or command."""
    try:
        if actor.kind == "temporary" or provider is None:
            raise PermissionError(_DENIED)
        resolve_principal(actor.principal)
        request = AuthorizationRequest(
            actor.principal,
            "installation.manage_principals",
            TargetRef("installation"),
            ResourceScope("installation"),
            actor.ceiling,
        )
        if not provider.check(request).allowed:
            raise PermissionError(_DENIED)
    except Exception as exc:
        raise PermissionError(_DENIED) from exc
