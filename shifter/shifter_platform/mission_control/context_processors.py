"""Context processors for mission_control app."""

from mission_control.models import Range


def active_range(request):
    """
    Add active range information to template context.

    Provides:
        - has_active_range: Boolean indicating if user has a ready range
        - active_range: The user's active Range object (or None)
    """
    if not request.user.is_authenticated:
        return {
            "has_active_range": False,
            "active_range": None,
        }

    # Get the user's active range (includes provisioning, ready, paused, etc.)
    user_range = Range.get_active_for_user(request.user)

    # Terminal is only available when range is ready
    has_ready_range = user_range is not None and user_range.status == Range.Status.READY

    return {
        "has_active_range": has_ready_range,
        "active_range": user_range,
    }
