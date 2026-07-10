"""Permission classes for Risk Register API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rest_framework import permissions
from rest_framework.request import Request

from risk_register.access import principal_has_risk_register_access
from risk_register.models import AuditLog
from risk_register.services import audit_log_from_request
from shared.api_tokens.models import ApiToken

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class AuditedPermissionMixin:
    """Mixin to log permission denied events to audit log."""

    def _log_permission_denied(self, request, view, message: str = ""):
        """Log access denied event to audit log."""
        try:
            # Determine entity type from view
            entity_type = AuditLog.EntityType.CONFIG  # Default
            entity_id = 0

            # Try to get entity info from view
            view_name = getattr(view, "__class__", type(view)).__name__
            if hasattr(view, "basename"):
                basename = view.basename
                if basename == "risk":
                    entity_type = AuditLog.EntityType.RISK
                elif basename == "auditlog":
                    entity_type = AuditLog.EntityType.CONFIG

            # Get entity_id from URL kwargs if available
            if hasattr(view, "kwargs") and view.kwargs:
                entity_id = view.kwargs.get("pk", 0) or view.kwargs.get("risk_pk", 0)

            context = f"Permission denied: {view_name}"
            if message:
                context = f"{context} - {message}"

            audit_log_from_request(
                request,
                entity_type=entity_type,
                entity_id=entity_id,
                action=AuditLog.Action.ACCESS_DENIED,
                context=context,
            )
        except Exception:
            # Never break the request flow for audit logging failures
            logger.exception("Failed to log permission denied event")


class HasRiskRegisterCognitoGroup(AuditedPermissionMixin, permissions.BasePermission):
    """Require membership in a configured Cognito group for risk register access."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        if principal_has_risk_register_access(request):
            return True
        self._log_permission_denied(request, view, "Not in allowed Cognito group")
        return False


class IsAdminUser(AuditedPermissionMixin, permissions.BasePermission):
    """
    Allow access only to admin users (staff or superuser).

    Platform API tokens carry no Django user and so are not admins; they are
    denied here without a special case.
    """

    def has_permission(self, request, view):
        # Must be authenticated user with staff/superuser status
        has_permission = bool(
            request.user and request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)
        )
        if not has_permission:
            self._log_permission_denied(request, view, "User is not admin")
        return has_permission


class IsStaffSessionOrToken(AuditedPermissionMixin, permissions.BasePermission):
    """Allow a platform API token (its scope is its authorization, checked by a
    sibling ``RequireScope`` permission) OR a staff/superuser session.

    Anonymous requests and non-admin sessions are denied. Compose with
    ``shared.api_tokens.permissions.RequireScope`` so token requests still must
    carry the required scope.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        # A scoped platform ApiToken is admitted here; the sibling require_scope
        # permission enforces the specific scope.
        if isinstance(request.auth, ApiToken):
            return True

        has_permission = bool(
            request.user and request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)
        )
        if not has_permission:
            self._log_permission_denied(request, view, "Not an admin session or scoped token")
        return has_permission


class IsOwnerOrAdmin(AuditedPermissionMixin, permissions.BasePermission):
    """
    Allow access if user owns the object or is an admin.
    """

    @staticmethod
    def _is_admin(request: Request) -> bool:
        return bool(
            request.user and request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)
        )

    @staticmethod
    def _owns_via_user(request: Request, obj: object) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        if getattr(obj, "author_user", None) == request.user:
            return True
        return getattr(obj, "created_by", None) == request.user

    def has_object_permission(self, request, view, obj):
        if self._is_admin(request) or self._owns_via_user(request, obj):
            return True

        # Log access denied
        obj_name = type(obj).__name__
        obj_id = getattr(obj, "id", "unknown")
        self._log_permission_denied(request, view, f"Not owner of object {obj_name}:{obj_id}")
        return False
