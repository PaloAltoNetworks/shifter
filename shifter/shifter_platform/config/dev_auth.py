"""Development authentication bypass.

WARNING: This module provides authentication bypass for development environments ONLY.
All views check settings.DEBUG or settings.ENVIRONMENT and return 403 Forbidden in production.
"""

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

User = get_user_model()


def _is_dev_environment():
    """Check if running in a development environment.

    Returns True if either:
    - DEBUG is True (local development), OR
    - ENVIRONMENT is 'development' (deployed dev environment via SSM tunnel)

    This allows dev_login to work both locally and in deployed dev when accessed via SSM tunnel.
    """
    return settings.DEBUG or getattr(settings, "ENVIRONMENT", "production") == "development"


def dev_login(request):
    """Quick login for development - creates/logs in a test user.

    SECURITY: Returns 403 unless in development environment (local or deployed dev).
    This is checked FIRST, before any other logic runs.

    Access patterns:
    - Local: Works when DEBUG=True
    - Dev (via SSM tunnel): Works when ENVIRONMENT='development'
    - Prod: Always blocked (ENVIRONMENT='production')
    """
    if not _is_dev_environment():
        return HttpResponseForbidden("Development auth disabled in production")

    if request.method == "POST":
        email = request.POST.get("email", "dev@example.com")
        user, _created = User.objects.get_or_create(username=email, defaults={"email": email, "is_active": True})
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return HttpResponseRedirect(reverse("mission_control:dashboard"))

    return render(request, "dev_login.html")


def dev_logout(request):
    """Quick logout for development.

    SECURITY: Returns 403 unless in development environment (local or deployed dev).
    """
    if not _is_dev_environment():
        return HttpResponseForbidden("Development auth disabled in production")

    from django.contrib.auth import logout

    logout(request)
    return HttpResponseRedirect("/")
