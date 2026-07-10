"""Development authentication bypass.

WARNING: This module provides authentication bypass for development environments ONLY.
All views check settings.DEBUG or settings.ENVIRONMENT and return 403 Forbidden in production.
"""

import ipaddress
import logging

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpRequest, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from config.user_type_sync import sync_user_type
from shared.log_sanitize import safe_log_value

# SonarCloud S1192: extracted duplicated string literals.
DASHBOARD_URL = "mission_control:dashboard"

logger = logging.getLogger(__name__)

User = get_user_model()

# Valid user types for dev login
VALID_DEV_USER_TYPES = {"standard", "ctf_organizer", "ctf_participant"}

# Redirect URLs by user type
USER_TYPE_REDIRECTS = {
    "standard": DASHBOARD_URL,
    "ctf_organizer": "ctf:admin_dashboard",
    "ctf_participant": DASHBOARD_URL,
}


def _is_dev_environment():
    """Check if running in a development environment.

    Returns True if either:
    - DEBUG is True (local development), OR
    - ENVIRONMENT is 'development' (deployed dev environment via SSM tunnel)

    This allows dev_login to work both locally and in deployed dev when accessed via SSM tunnel.
    """
    # NOSONAR - intentional dev bypass, guarded by ENVIRONMENT; prod uses OIDC
    return settings.DEBUG or getattr(settings, "ENVIRONMENT", "production") == "development"


_IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _parse_peer_ip(remote_addr: str) -> _IpAddress | None:
    """Parse ``REMOTE_ADDR`` into an IP address, or None when absent/malformed."""
    remote_addr = remote_addr.strip()
    if not remote_addr:
        return None
    try:
        return ipaddress.ip_address(remote_addr)
    except ValueError:
        return None


def _ip_in_cidr(client_ip: _IpAddress, cidr: str) -> bool:
    """Return True if ``client_ip`` falls in ``cidr``; skip malformed CIDRs."""
    try:
        return client_ip in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        logger.warning("Ignoring invalid DEV_LOGIN_ALLOWED_CIDRS entry: %s", cidr)
        return False


def _request_peer_allowed(request: HttpRequest) -> bool:
    """Allow dev auth only from a trusted direct peer address.

    Admission is bound to the actual socket peer (``REMOTE_ADDR``) — never the
    spoofable ``Host`` header or ``X-Forwarded-For`` (SEC-3, issue #937). The
    loopback range is always admitted so local development and SSM/admin
    tunnels (which present as loopback) keep working; additional admin networks
    opt in through ``DEV_LOGIN_ALLOWED_CIDRS``.
    """
    client_ip = _parse_peer_ip(request.META.get("REMOTE_ADDR", ""))
    if client_ip is None:
        return False
    if client_ip.is_loopback:
        return True
    return any(_ip_in_cidr(client_ip, cidr) for cidr in getattr(settings, "DEV_LOGIN_ALLOWED_CIDRS", []))


def dev_login(request):
    """Quick login for development - creates/logs in a test user.

    SECURITY: Returns 403 unless in development environment (local or deployed dev).
    This is checked FIRST, before any other logic runs.

    Access patterns:
    - Local: Works when DEBUG=True
    - Dev (via SSM tunnel): Works when ENVIRONMENT='development'
    - Prod: Always blocked (ENVIRONMENT='production')

    Supports user_type POST parameter for CTF user types:
    - standard (default): redirects to mission control
    - ctf_organizer: redirects to CTF admin dashboard
    - ctf_participant: redirects to Mission Control dashboard
    """
    if not _is_dev_environment():
        return HttpResponseForbidden("Development auth disabled in production")
    if not settings.DEBUG and not _request_peer_allowed(request):
        return HttpResponseForbidden("Development auth is only available through local or admin access paths")

    if request.method == "POST":
        email = request.POST.get("email", "dev@example.com")
        user_type = request.POST.get("user_type", "standard")

        if user_type not in VALID_DEV_USER_TYPES:
            user_type = "standard"

        user, _created = User.objects.get_or_create(username=email, defaults={"email": email, "is_active": True})
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        # Sync CTF group membership + profile via the shared, audited helper so
        # dev-login produces the same fail-closed ROLE_SYNC audit trail as the
        # real identity providers (issue #937 SEC-5).
        sync_user_type(user, user_type, source="dev_login", request=request)
        logger.info("Dev login: set user_type=%s for %s", safe_log_value(user_type), safe_log_value(email))

        # Redirect to appropriate dashboard
        redirect_url = reverse(USER_TYPE_REDIRECTS.get(user_type, DASHBOARD_URL))
        return HttpResponseRedirect(redirect_url)

    return render(request, "dev_login.html")


def dev_logout(request):
    """Quick logout for development.

    SECURITY: Returns 403 unless in development environment (local or deployed dev).
    """
    if not _is_dev_environment():
        return HttpResponseForbidden("Development auth disabled in production")
    if not settings.DEBUG and not _request_peer_allowed(request):
        return HttpResponseForbidden("Development auth is only available through local or admin access paths")

    from django.contrib.auth import logout

    logout(request)
    return HttpResponseRedirect("/")
