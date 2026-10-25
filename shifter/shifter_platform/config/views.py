"""Simple views for the platform."""

import json
import logging
from typing import cast

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from config import identity_platform as identity_platform_auth
from shared.audit import (
    AuditAction,
    AuthPrincipal,
    audit_auth_event,
    get_client_ip,
)
from shared.errors import classify_user_message
from shared.log_sanitize import safe_log_fingerprint

# SonarCloud S1192: extracted duplicated string literals.
DASHBOARD_URL = "mission_control:dashboard"

logger = logging.getLogger(__name__)


def home(request: HttpRequest) -> HttpResponse:
    """Landing page - coming soon."""
    return render(request, "coming_soon.html")


@require_http_methods(["GET", "HEAD"])
def privacy_notice(request: HttpRequest) -> HttpResponse:
    """Public privacy notice shell for operator-supplied content."""
    return render(request, "privacy/notice.html")


def _render_identity_platform_login(request: HttpRequest, *, status_code: int = 200) -> HttpResponse:
    """Render the Identity Platform login page for the current request."""
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
                "verificationContinueUrl": f"{site_url}{reverse('platform_login')}",
            },
        },
        status=status_code,
    )


def _render_identity_platform_logout(request: HttpRequest) -> HttpResponse:
    """Render the Identity Platform logout page for the current request."""
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


def _login_response_for_provider(request: HttpRequest) -> HttpResponse:
    """Return the login response for the configured authentication provider."""
    if settings.AUTH_PROVIDER == "oidc":
        return HttpResponseRedirect(reverse("oidc_authentication_init"))
    if settings.AUTH_PROVIDER != "identity_platform":
        return HttpResponseForbidden("Unsupported auth provider")
    return _render_identity_platform_login(request)


@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def platform_login(request: HttpRequest) -> HttpResponse:
    """Route authentication to the configured provider."""
    if request.user.is_authenticated:
        from config.workspace_invitation_auth import preserve_staged_invitation_across_logout
        from shared.workspace_invitation_handoff import STAGED_INVITATION_SESSION_KEY

        staged = preserve_staged_invitation_across_logout(request)
        if staged is None:
            return HttpResponseRedirect(reverse("dashboard_router"))
        logout(request)
        request.session[STAGED_INVITATION_SESSION_KEY] = staged

    return _login_response_for_provider(request)


def _parse_id_token(request: HttpRequest) -> str:
    """Extract and validate the ID token from the request body, raising ``ValueError`` on bad input."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON.") from exc
    id_token = str(payload.get("idToken", "")).strip()
    if not id_token:
        raise ValueError("An ID token is required.")
    return id_token


def _authenticate_and_respond(request: HttpRequest, id_token: str) -> JsonResponse:
    """Authenticate the ID token, establish a Django session, and return the redirect payload."""
    try:
        user = identity_platform_auth.login_with_identity_token(request, id_token)
    except identity_platform_auth.IdentityPlatformAuthError as exc:
        # Retain only a fixed code and an opaque correlation fingerprint. The
        # provider response can contain confidential request context, so it is
        # neither logged nor returned to the caller.
        logger.warning(
            "identity_platform_session: authentication failed code=%s reason=%s",
            exc.code,
            safe_log_fingerprint(exc),
        )
        return JsonResponse(
            {"error": exc.code, "message": classify_user_message(str(exc), default="Authentication failed")},
            status=403,
        )

    login(request, user, backend="config.identity_platform.IdentityPlatformBackend")
    from config.session_credentials import establish_identity_session

    establish_identity_session(request.session, request.verified_session_claims)  # type: ignore[attr-defined]
    return JsonResponse({"redirect_url": reverse("dashboard_router")})


@require_POST
def identity_platform_session(request: HttpRequest) -> HttpResponse:
    """Create a Django session from a verified Identity Platform ID token."""
    if settings.AUTH_PROVIDER != "identity_platform":
        return JsonResponse({"error": "unsupported_auth_provider"}, status=403)

    try:
        id_token = _parse_id_token(request)
    except ValueError as exc:
        # Log the specific parse failure server-side; return a fixed generic
        # message so no exception detail is exposed to the caller (CodeQL
        # py/stack-trace-exposure).
        logger.info("identity_platform_session: rejected malformed request: %s", exc)
        return JsonResponse({"error": "invalid_request", "message": "Invalid authentication request."}, status=400)

    return _authenticate_and_respond(request, id_token)


@require_http_methods(["GET", "HEAD"])
def legacy_oidc_authenticate(request: HttpRequest) -> HttpResponse:
    """Keep the AWS login URL stable while redirecting GCP deployments to the provider router."""
    if settings.AUTH_PROVIDER == "oidc":
        from mozilla_django_oidc.views import OIDCAuthenticationRequestView

        return OIDCAuthenticationRequestView.as_view()(request)
    return HttpResponseRedirect(reverse("platform_login"))


@require_http_methods(["GET", "HEAD"])
@login_required
def dashboard_router(request: HttpRequest) -> HttpResponse:
    """Route authenticated users to the role-aware SPA home/dashboard."""
    from config.workspace_invitation_auth import pop_post_login_continuation

    continuation = pop_post_login_continuation(request)
    if continuation is not None:
        return HttpResponseRedirect(continuation)
    user = cast(User, request.user)
    logger.debug(
        "Routing user=%s to the platform SPA dashboard",
        safe_log_fingerprint(user.email),
    )
    return HttpResponseRedirect(reverse("home"))


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    """Log out the current user, routing to the correct logout mechanism.

    OIDC users (authenticated via ShifterOIDCBackend) get their Django
    session cleared and are redirected to Cognito's logout endpoint to
    also clear the identity provider session.

    All other users (local CTF participants, dev-login) get a
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
        action=AuditAction.LOGOUT,
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
        logger.debug("OIDC logout for user=%s", safe_log_fingerprint(email))
    elif "IdentityPlatformBackend" in backend:
        logger.debug("Identity Platform logout for user=%s", safe_log_fingerprint(email))
    else:
        logger.debug("Session logout for user=%s", safe_log_fingerprint(email))

    logout(request)
    if "IdentityPlatformBackend" in backend:
        return _render_identity_platform_logout(request)
    return HttpResponseRedirect(redirect_url)
