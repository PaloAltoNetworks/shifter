"""Audit seam for API-token lifecycle events (PLAT-102).

The platform token principal lives in ``shared``; its durable audit trail lives
in ``risk_register`` (the canonical platform audit store the whole platform
already uses). This seam keeps the ``shared.api_tokens`` package free of an
app-layer dependency at import time by resolving ``risk_register.services``
lazily, inside the call — the only place a ``shared`` -> app reference exists,
and only when an event is actually recorded.

Only token **creation**, **revocation**, and **authentication failure** are
recorded. Successful authentication is deliberately not audited per-request to
avoid write amplification once tokens cover high-frequency automation;
``ApiToken.last_used_at`` (coalesced) provides liveness instead.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.http import HttpRequest


class TokenEvent(Enum):
    """High-level token audit events (mapped to AuditLog actions at the edge)."""

    CREATED = "created"
    REVOKED = "revoked"
    AUTH_FAILED = "auth_failed"


def record_token_event(
    event: TokenEvent,
    *,
    request: HttpRequest | None = None,
    token_id: str | None = None,
    token_pk: int | None = None,
    actor_id: int | None = None,
    context: str = "",
) -> None:
    """Record a token lifecycle event in the platform audit log.

    ``token_id`` is the public, non-secret lookup id; the raw token/secret is
    never passed here. Failures are swallowed by the underlying ``audit_log``
    (audit logging never breaks the caller).
    """
    # Lazy, call-local import: keeps shared.api_tokens import-clean of the app
    # layer (see module docstring).
    from risk_register.models import AuditLog
    from risk_register.services import (
        AuditEvent,
        audit_log,
        get_client_ip,
        get_request_id,
    )

    action_by_event = {
        TokenEvent.CREATED: AuditLog.Action.CREATE,
        TokenEvent.REVOKED: AuditLog.Action.DELETE,
        TokenEvent.AUTH_FAILED: AuditLog.Action.LOGIN_FAILED,
    }
    # Creation and revocation are browser-session admin actions performed by a
    # staff/superuser (actor_id is their user id); only the authentication
    # failure is attributable to the token principal itself.
    actor_type_by_event = {
        TokenEvent.CREATED: AuditLog.ActorType.USER,
        TokenEvent.REVOKED: AuditLog.ActorType.USER,
        TokenEvent.AUTH_FAILED: AuditLog.ActorType.APIKEY,
    }

    source_ip = None
    user_agent = ""
    request_id = ""
    if request is not None:
        source_ip = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]
        request_id = get_request_id(request)

    new_state = {"token_id": token_id} if token_id else None

    audit_log(
        AuditEvent(
            entity_type=AuditLog.EntityType.APIKEY,
            entity_id=token_pk or 0,
            action=action_by_event[event],
            actor_type=actor_type_by_event[event],
            actor_id=actor_id,
            new_state=new_state,
            context=context,
            source_ip=source_ip,
            user_agent=user_agent,
            request_id=request_id,
        )
    )
