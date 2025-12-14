"""Permission classes for Risk Register API."""

from rest_framework import permissions

from risk_register.models import APIKey


class IsAuthenticatedOrAPIKey(permissions.BasePermission):
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

        return False


class IsAdminUser(permissions.BasePermission):
    """
    Allow access only to admin users (staff or superuser).
    API keys cannot access admin-only endpoints.
    """

    def has_permission(self, request, view):
        # API keys cannot access admin endpoints
        if isinstance(request.auth, APIKey):
            return False

        # Must be authenticated user with staff/superuser status
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        )


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Allow access if user owns the object or is an admin.
    For API keys, allow access to objects they created.
    """

    def has_object_permission(self, request, view, obj):
        # Admins can access anything
        if request.user and request.user.is_authenticated:
            if request.user.is_staff or request.user.is_superuser:
                return True

        # Check ownership for API keys
        if isinstance(request.auth, APIKey):
            # For comments, check if API key is the author
            if hasattr(obj, "author_apikey") and obj.author_apikey == request.auth:
                return True

        # Check ownership for users
        if request.user and request.user.is_authenticated:
            if hasattr(obj, "author_user") and obj.author_user == request.user:
                return True
            if hasattr(obj, "created_by") and obj.created_by == request.user:
                return True

        return False
