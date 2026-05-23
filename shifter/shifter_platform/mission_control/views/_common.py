"""Shared helpers, constants, and late-binding glue for mission_control views.

Tests historically patch names at ``mission_control.views.<name>`` (via
``patch("mission_control.views.X")`` or ``patch.object(views, "X")``).
The package ``__init__`` re-exports those names; submodules must call
through the ``_via_pkg`` helpers in this module so the patches take
effect at call time.
"""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth.models import User
from django.http import HttpRequest

from risk_register.models import AuditLog

GUAC_AUTH_NOT_CONFIGURED = "Guacamole JSON auth is not configured"
GUACAMOLE_BASE_PATH = "/guacamole"
INTERNAL_SERVER_ERROR = "Internal server error"
NGFW_NOT_FOUND = "NGFW not found"


def _pkg() -> Any:
    """Return the ``mission_control.views`` package module (for late-binding)."""
    from mission_control import views as _v

    return _v


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
    extra_state: dict | None = None,
) -> None:
    """Record an HTTP-layer audit entry for a range lifecycle action.

    Captures source IP, user agent, and HTTP request ID from the request via
    ``risk_register.services.audit_log_from_request``. Complements the CMS
    service-layer audit entries by attaching request context.

    range_id (legacy) or range_request_id (UUID) identifies the range.
    """
    new_state: dict = {}
    if range_request_id:
        new_state["request_id"] = range_request_id
    if range_id is not None:
        new_state["range_id"] = range_id
    if extra_state:
        new_state.update(extra_state)
    # Late-bind so tests can ``patch.object(views, "audit_log_from_request")``.
    _pkg().audit_log_from_request(
        request,
        entity_type=AuditLog.EntityType.RANGE,
        entity_id=range_id or 0,
        action=action,
        new_state=new_state or None,
    )


# -- Late-binding helpers for names tests patch at the package level ----------


def _render_via_pkg(*args: Any, **kwargs: Any) -> Any:
    """Late-bound call to ``mission_control.views.render``."""
    return _pkg().render(*args, **kwargs)


def _cms_list_agents_via_pkg(*args: Any, **kwargs: Any) -> Any:
    """Late-bound call to ``mission_control.views.cms_list_agents``."""
    return _pkg().cms_list_agents(*args, **kwargs)


def _cms_delete_agent_via_pkg(*args: Any, **kwargs: Any) -> Any:
    """Late-bound call to ``mission_control.views.cms_delete_agent``."""
    return _pkg().cms_delete_agent(*args, **kwargs)


def _cms_get_ngfw_via_pkg(*args: Any, **kwargs: Any) -> Any:
    """Late-bound call to ``mission_control.views.cms_get_ngfw``."""
    return _pkg().cms_get_ngfw(*args, **kwargs)


def _get_allowed_extensions_via_pkg(*args: Any, **kwargs: Any) -> Any:
    """Late-bound call to ``mission_control.views.get_allowed_extensions``."""
    return _pkg().get_allowed_extensions(*args, **kwargs)


def _logger() -> Any:
    """Return the shared ``mission_control.views.logger`` (late-bound)."""
    return _pkg().logger
