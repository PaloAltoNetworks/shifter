"""Permission classes for Scenario Editor."""

from rest_framework import permissions


class IsStaffUser(permissions.BasePermission):
    """Allow access only to staff users (is_staff or is_superuser).

    Used for all scenario editor endpoints since only staff
    should be able to create, edit, or manage scenarios.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        )
