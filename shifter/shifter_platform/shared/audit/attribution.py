"""Trusted request attribution for audit events (neutral contracts layer).

Canonical HTTP/ASGI attribution contract for audit source IP, request id, and
actor. One resolver for all consumers: trust the configured rightmost proxy hop
and fall back to ``REMOTE_ADDR``; never trust the client-controlled leftmost
``X-Forwarded-For`` entry (SEC-4, issue #937). Moved from
the former feature-owned module into ``shared`` in #1523 so emitters use one
neutral boundary.
"""

from __future__ import annotations

import ipaddress
import uuid
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID

from django.conf import settings

from shared.audit.vocabulary import AuditActorType

if TYPE_CHECKING:
    from django.http import HttpRequest

    from shared.audit.events import RequestAudit
    from shared.credentials import CredentialContext
    from shared.identity_scope import PrincipalRef


class PrincipalActorFields(TypedDict):
    """Keyword fields that identify a principal actor on an audit event."""

    actor_type: str
    actor_id: int | None
    actor_principal_uuid: UUID


def principal_actor_fields(principal: PrincipalRef) -> PrincipalActorFields:
    """Canonical attribution for an already-authorized neutral principal."""
    from shared.identity_scope import PrincipalRef

    if not isinstance(principal, PrincipalRef):
        raise ValueError("Invalid audit principal")
    return {"actor_type": AuditActorType.PRINCIPAL, "actor_id": None, "actor_principal_uuid": principal.uuid}


def request_audit(request: HttpRequest, *, credential: CredentialContext | None = None) -> RequestAudit:
    """Capture trusted identity and HTTP metadata, never caller-supplied actor fields.

    Preserve legacy user/token attribution when available and supplement it with
    the durable principal. Native services have no integer actor and use the
    principal form exclusively.
    """
    from shared.audit.events import RequestAudit
    from shared.credentials import CredentialContext

    if credential is None:
        candidate = getattr(request, "credential_context", None)
        if isinstance(candidate, CredentialContext):
            credential = candidate
    request_auth = getattr(request, "auth", None)
    if credential is None and isinstance(request_auth, CredentialContext):
        credential = request_auth
    actor_type, actor_id = get_actor_from_request(request)
    principal_uuid = None
    if credential is not None:
        if not isinstance(credential, CredentialContext):
            raise ValueError("Invalid audit credential")
        principal_uuid = credential.principal.uuid
        if credential.kind == "service" or actor_type == AuditActorType.SYSTEM:
            actor_type, actor_id = AuditActorType.PRINCIPAL, None
    return RequestAudit(
        actor_type=actor_type,
        actor_id=actor_id,
        actor_principal_uuid=principal_uuid,
        source_ip=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        request_id=get_request_id(request)[:64],
    )


def _valid_ip(value: str | None) -> str | None:
    """Return ``value`` if it parses as an IP address, else ``None``."""
    if not value:
        return None
    candidate = value.strip()
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return candidate


def select_trusted_client_ip(
    xff_value: str | None,
    remote_addr: str | None,
    *,
    trusted_hops: int = 1,
) -> str | None:
    """Resolve the client IP from an ``X-Forwarded-For`` chain plus direct peer.

    Behind ``trusted_hops`` reverse proxies that each append the address they
    received the request from, the trustworthy client value is the
    ``trusted_hops``-th entry counted from the **right** — the rightmost entry
    is the nearest proxy's view of its peer (the value the ALB appends).
    Everything to the left of that is client-supplied and therefore spoofable,
    so it is never trusted. When the chain is absent, shorter than the trusted
    hop count, or the selected token is not a valid IP, fall back to the direct
    peer ``remote_addr`` (SEC-4, issue #937).
    """
    hops = trusted_hops if trusted_hops and trusted_hops > 0 else 1
    if xff_value:
        parts = [part.strip() for part in xff_value.split(",") if part.strip()]
        if len(parts) >= hops:
            selected = _valid_ip(parts[-hops])
            if selected is not None:
                return selected
    return _valid_ip(remote_addr)


def get_client_ip(request: HttpRequest) -> str | None:
    """Extract the trusted client IP for audit attribution.

    Delegates to :func:`select_trusted_client_ip` using
    ``settings.AUDIT_TRUSTED_PROXY_HOPS`` so the leftmost (attacker-controlled)
    ``X-Forwarded-For`` value is never trusted behind the load balancer.

    Args:
        request: Django HttpRequest

    Returns:
        Client IP address or None
    """
    trusted_hops = getattr(settings, "AUDIT_TRUSTED_PROXY_HOPS", 1)
    return select_trusted_client_ip(
        request.META.get("HTTP_X_FORWARDED_FOR"),
        request.META.get("REMOTE_ADDR"),
        trusted_hops=trusted_hops,
    )


def get_request_id(request: HttpRequest) -> str:
    """Extract or generate request ID from request.

    Args:
        request: Django HttpRequest

    Returns:
        Request ID string
    """
    # Check for existing request ID from header or middleware
    request_id = getattr(request, "request_id", None)
    if request_id:
        return request_id

    # Check X-Request-ID header
    request_id = request.META.get("HTTP_X_REQUEST_ID")
    if request_id:
        return request_id

    # Generate a new one
    return str(uuid.uuid4())[:8]


def get_actor_from_request(request: HttpRequest) -> tuple[str, int | None]:
    """Extract actor type and ID from request.

    Handles both user authentication and API key authentication.

    Args:
        request: Django HttpRequest

    Returns:
        Tuple of (actor_type, actor_id)
    """
    # Check for authenticated user
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return (AuditActorType.USER, user.id)

    # Check for API key authentication (from DRF request.auth)
    auth = getattr(request, "auth", None)
    if auth and hasattr(auth, "id"):
        return (AuditActorType.APIKEY, auth.id)

    # Unknown actor
    return (AuditActorType.SYSTEM, None)
