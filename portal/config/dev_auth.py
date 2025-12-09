"""Development authentication bypass.

WARNING: This module provides authentication bypass for local development ONLY.
All views check settings.DEBUG and return 403 Forbidden in production.
"""

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

User = get_user_model()


def dev_login(request):
    """Quick login for development - creates/logs in a test user.

    SECURITY: Returns 403 if DEBUG is False. This is checked FIRST,
    before any other logic runs.
    """
    if not settings.DEBUG:
        return HttpResponseForbidden("Development auth disabled in production")

    if request.method == "POST":
        email = request.POST.get("email", "dev@example.com")
        user, created = User.objects.get_or_create(
            username=email,
            defaults={"email": email, "is_active": True}
        )
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return HttpResponseRedirect(reverse("mission_control:dashboard"))

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
