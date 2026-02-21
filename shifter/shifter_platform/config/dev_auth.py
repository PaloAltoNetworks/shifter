"""Development authentication bypass.

WARNING: This module provides authentication bypass for local development ONLY.
All views check settings.DEBUG and return 403 Forbidden in production.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from management.services import get_user_profile

logger = logging.getLogger(__name__)

User = get_user_model()

# Valid user types for dev login
VALID_DEV_USER_TYPES = {"standard", "ctf_organizer", "ctf_participant"}

# Redirect URLs by user type
USER_TYPE_REDIRECTS = {
    "standard": "mission_control:dashboard",
    "ctf_organizer": "ctf:admin_dashboard",
    "ctf_participant": "ctf:participant_dashboard",
}


def dev_login(request):
    """Quick login for development - creates/logs in a test user.

    SECURITY: Returns 403 if DEBUG is False. This is checked FIRST,
    before any other logic runs.

    Supports user_type POST parameter for CTF user types:
    - standard (default): redirects to mission control
    - ctf_organizer: redirects to CTF admin dashboard
    - ctf_participant: redirects to CTF participant dashboard
    """
    if not settings.DEBUG:
        return HttpResponseForbidden("Development auth disabled in production")

    if request.method == "POST":
        email = request.POST.get("email", "dev@example.com")
        user_type = request.POST.get("user_type", "standard")

        if user_type not in VALID_DEV_USER_TYPES:
            user_type = "standard"

        user, _created = User.objects.get_or_create(
            username=email, defaults={"email": email, "is_active": True}
        )
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        # Set user type on profile
        profile = get_user_profile(user)
        if profile.user_type != user_type:
            profile.user_type = user_type
            profile.save(update_fields=["user_type"])
            logger.info("Dev login: set user_type=%s for %s", user_type, email)

        # Redirect to appropriate dashboard
        redirect_url = reverse(USER_TYPE_REDIRECTS.get(user_type, "mission_control:dashboard"))
        return HttpResponseRedirect(redirect_url)

    return render(request, "dev_login.html")


def dev_logout(request):
    """Quick logout for development.

    SECURITY: Returns 403 if DEBUG is False.
    """
    if not settings.DEBUG:
        return HttpResponseForbidden("Development auth disabled in production")

    from django.contrib.auth import logout

    logout(request)
    return HttpResponseRedirect("/")
