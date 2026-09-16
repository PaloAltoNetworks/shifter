"""Shared helpers and constants for mission_control views."""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth.models import User
from django.http import HttpRequest

from shared.audit import AuditEntityType, audit_log_from_request

GUAC_AUTH_NOT_CONFIGURED = "Guacamole JSON auth is not configured"
GUACAMOLE_BASE_PATH = "/guacamole"
INTERNAL_SERVER_ERROR = "Internal server error"
NGFW_NOT_FOUND = "NGFW not found"


def _get_user(request: HttpRequest) -> User:
    """Get authenticated user from request. Use only in @login_required views."""
    assert request.user.is_authenticated, "View must use @login_required"
    return cast(User, request.user)


def _audit_range_lifecycle(
    request: HttpRequest,
    action: str,
    *,
    range_id: int | None = None,
    range_request_id: str | None = None,
    extra_state: dict[str, Any] | None = None,
) -> None:
    """Record an HTTP-layer audit entry for a range lifecycle action.

    Captures source IP, user agent, and HTTP request ID from the request via
    ``shared.audit.audit_log_from_request``. Complements the CMS
    service-layer audit entries by attaching request context.

    range_id (legacy) or range_request_id (UUID) identifies the range.
    """
    new_state: dict[str, Any] = {}
    if range_request_id:
        new_state["request_id"] = range_request_id
    if range_id is not None:
        new_state["range_id"] = range_id
    if extra_state:
        new_state.update(extra_state)
    audit_log_from_request(
        request,
        entity_type=AuditEntityType.RANGE,
        entity_id=range_id or 0,
        action=action,
        new_state=new_state or None,
    )
