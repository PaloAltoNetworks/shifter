"""Simple views for the platform."""

import json
import logging

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from config import identity_platform as identity_platform_auth
from risk_register.models import AuditLog
from risk_register.services import AuthPrincipal, audit_auth_event, get_client_ip
from shared.auth import is_ctf_organizer, is_ctf_participant
from shared.errors import classify_user_message

# SonarCloud S1192: extracted duplicated string literals.
DASHBOARD_URL = "mission_control:dashboard"

logger = logging.getLogger(__name__)


def home(request):
    """Landing page - coming soon."""
    return render(request, "coming_soon.html")


@require_http_methods(["GET", "HEAD"])
def privacy_notice(request: HttpRequest) -> HttpResponse:
    """Public privacy notice shell for operator-supplied content."""
    return render(request, "privacy/notice.html")


def _render_identity_platform_login(request, *, status_code: int = 200):
    client_config = identity_platform_auth.identity_platform_client_config()
    site_url = (settings.SITE_URL or "").rstrip("/") or request.build_absolute_uri("/").rstrip("/")
    return render(
        request,
        "identity_platform_login.html",
        {
            # Pass the dict itself; the template's `json_script` filter does the
            # single JSON encoding. Pre-serializing here would double-encode, so
            # the browser's JSON.parse would yield a string and config.apiKey
            # would be undefined (Firebase init then fails auth/invalid-api-key).
            "identity_platform_config_json": {
                **client_config,
                "sessionExchangeUrl": reverse("identity_platform_session"),
                "dashboardUrl": reverse("dashboard_router"),
                "loginUrl": reverse("platform_login"),
                "passwordResetUrl": reverse("platform_login"),
                "verificationContinueUrl": f"{site_url}{reverse('platform_login')}",
            },
            "allowed_email_domain": client_config["allowedEmailDomain"],
        },
        status=status_code,
    )


def _render_identity_platform_logout(request):
    client_config = identity_platform_auth.identity_platform_client_config()
    return render(
        request,
        "identity_platform_logout.html",
        {
            # Pass the dict; the template's `json_script` filter encodes once.
            # (See _render_identity_platform_login for the double-encode hazard.)
            "identity_platform_logout_config_json": {
                **client_config,
                "redirectUrl": settings.LOGOUT_REDIRECT_URL,
                "loginUrl": reverse("platform_login"),
            }
        },
    )


@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def platform_login(request):
    """Route authentication to the configured provider."""
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse("dashboard_router"))

    if settings.AUTH_PROVIDER == "oidc":
        return HttpResponseRedirect(reverse("oidc_authentication_init"))
    if settings.AUTH_PROVIDER != "identity_platform":
        return HttpResponseForbidden("Unsupported auth provider")

    return _render_identity_platform_login(request)


@require_POST
def identity_platform_session(request):
    """Create a Django session from a verified Identity Platform ID token."""
    if settings.AUTH_PROVIDER != "identity_platform":
        return JsonResponse({"error": "unsupported_auth_provider"}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_request", "message": "Request body must be valid JSON."}, status=400)

    id_token = str(payload.get("idToken", "")).strip()
    if not id_token:
        return JsonResponse({"error": "invalid_request", "message": "An ID token is required."}, status=400)

    try:
        user = identity_platform_auth.login_with_identity_token(request, id_token)
    except identity_platform_auth.IdentityPlatformAuthError as exc:
        # Log the full detail server-side; return only the fixed-vocabulary code
        # plus a classified, non-tainted message so upstream exception text
        # (e.g. an Identity Platform API response body) cannot leak to the caller
        # (CodeQL py/stack-trace-exposure).
        logger.exception("identity_platform_session: authentication failed (code=%s)", exc.code)
        return JsonResponse(
            {"error": exc.code, "message": classify_user_message(str(exc), default="Authentication failed")},
            status=403,
        )

    login(request, user, backend="config.identity_platform.IdentityPlatformBackend")
    return JsonResponse({"redirect_url": reverse("dashboard_router")})


@require_http_methods(["GET", "HEAD"])
def legacy_oidc_authenticate(request):
    """Keep the AWS login URL stable while redirecting GCP deployments to the provider router."""
    if settings.AUTH_PROVIDER == "oidc":
        from mozilla_django_oidc.views import OIDCAuthenticationRequestView

        return OIDCAuthenticationRequestView.as_view()(request)
    return HttpResponseRedirect(reverse("platform_login"))


@login_required
def dashboard_router(request):
    """Route authenticated users to the correct dashboard based on user type.

    - standard users -> Mission Control dashboard
    - ctf_organizer -> CTF Admin dashboard
    - ctf_participant -> Mission Control dashboard (with restricted nav)
    """
    if is_ctf_organizer(request.user):
        logger.debug("Routing organizer %s to Mission Control dashboard", request.user.email)
        return HttpResponseRedirect(reverse(DASHBOARD_URL))
    elif is_ctf_participant(request.user):
        logger.debug("Routing participant %s to Mission Control dashboard", request.user.email)
        return HttpResponseRedirect(reverse(DASHBOARD_URL))
    else:
        logger.debug("Routing standard user %s to Mission Control", request.user.email)
        return HttpResponseRedirect(reverse(DASHBOARD_URL))


@require_POST
def logout_view(request):
    """Log out the current user, routing to the correct logout mechanism.

    OIDC users (authenticated via ShifterOIDCBackend) get their Django
    session cleared and are redirected to Cognito's logout endpoint to
    also clear the identity provider session.

    All other users (magic-link CTF participants, dev-login) get a
    simple Django session logout and redirect to the landing page.
    """
    if not request.user.is_authenticated:
        return HttpResponseRedirect(settings.LOGOUT_REDIRECT_URL)

    backend = request.session.get(BACKEND_SESSION_KEY, "")
    email = request.user.email
    redirect_url = settings.LOGOUT_REDIRECT_URL

    # Capture the audit identity and request context before Django ``logout``
    # flushes the session below.
    audit_auth_event(
        action=AuditLog.Action.LOGOUT,
        principal=AuthPrincipal(user_id=request.user.id, email=email),
        source_ip=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        context="Portal logout",
    )

    if "OIDCAuthenticationBackend" in backend:
        # Build the Cognito logout URL before clearing the session,
        # since provider_logout_url needs the request for the redirect URI.
        logout_url_method = getattr(settings, "OIDC_OP_LOGOUT_URL_METHOD", "")
        if logout_url_method:
            from django.utils.module_loading import import_string

            redirect_url = import_string(logout_url_method)(request)
        logger.debug("OIDC logout for %s", email)
    elif "IdentityPlatformBackend" in backend:
        logger.debug("Identity Platform logout for %s", email)
    else:
        logger.debug("Session logout for %s", email)

    logout(request)
    if "IdentityPlatformBackend" in backend:
        return _render_identity_platform_logout(request)
    return HttpResponseRedirect(redirect_url)
