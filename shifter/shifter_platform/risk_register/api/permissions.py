"""Permission classes for Risk Register API."""

import logging

from rest_framework import permissions

from risk_register.models import APIKey, AuditLog
from risk_register.services import audit_log_from_request

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


class IsAuthenticatedOrAPIKey(AuditedPermissionMixin, permissions.BasePermission):
    """
    Allow access if user is authenticated OR valid API key is provided.
    """

    def has_permission(self, request, view):
        # Check for authenticated user
        if request.user and request.user.is_authenticated:
            return True

        # Check for API key authentication
        if isinstance(request.auth, APIKey):
            return True

        # Log access denied
        self._log_permission_denied(request, view, "No valid authentication")
        return False


class IsAdminUser(AuditedPermissionMixin, permissions.BasePermission):
    """
    Allow access only to admin users (staff or superuser).
    API keys cannot access admin-only endpoints.
    """

    def has_permission(self, request, view):
        # API keys cannot access admin endpoints
        if isinstance(request.auth, APIKey):
            self._log_permission_denied(request, view, "API key not allowed for admin endpoint")
            return False

        # Must be authenticated user with staff/superuser status
        has_permission = bool(
            request.user and request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)
        )
        if not has_permission:
            self._log_permission_denied(request, view, "User is not admin")
        return has_permission


class IsOwnerOrAdmin(AuditedPermissionMixin, permissions.BasePermission):
    """
    Allow access if user owns the object or is an admin.
    For API keys, allow access to objects they created.
    """

    def has_object_permission(self, request, view, obj):
        # Admins can access anything
        if request.user and request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
            return True

        # Check ownership for API keys
        if isinstance(request.auth, APIKey) and hasattr(obj, "author_apikey") and obj.author_apikey == request.auth:
            return True

        # Check ownership for users
        if request.user and request.user.is_authenticated:
            if hasattr(obj, "author_user") and obj.author_user == request.user:
                return True
            if hasattr(obj, "created_by") and obj.created_by == request.user:
                return True

        # Log access denied
        self._log_permission_denied(request, view, f"Not owner of object {type(obj).__name__}:{getattr(obj, 'id', 'unknown')}")
        return False
