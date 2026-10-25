"""Installation-scoped policy boundary for immutable audit reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import QuerySet

from shared.authorization import AuthorizationProvider, AuthorizationRequest, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from shared.principal_port import resolve_principal

if TYPE_CHECKING:
    from shared.models import AuditLog

_DENIED = "Audit read denied"


class AuditReadDenied(ValueError):
    """The global audit ledger is unavailable to this application principal."""


def authorized_audit_events(actor: CredentialContext, provider: AuthorizationProvider) -> QuerySet[AuditLog]:
    """Grant the global ledger only to a live installation audit authority.

    The ledger has no trustworthy customer scope on historical rows. Callers
    must filter this authorized queryset before pagination or export.
    """
    try:
        if actor.kind == "temporary":
            raise AuditReadDenied(_DENIED)
        resolve_principal(actor.principal)
        request = AuthorizationRequest(
            actor.principal,
            "installation.read_audit",
            TargetRef("installation"),
            ResourceScope("installation"),
            actor.ceiling,
        )
        if not provider.check(request).allowed:
            raise AuditReadDenied(_DENIED)
    except Exception as exc:
        raise AuditReadDenied(_DENIED) from exc
    from shared.models import AuditLog

    return AuditLog.objects.all()
