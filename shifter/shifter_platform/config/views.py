"""Simple views for the platform."""

import logging

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from config import identity_platform as identity_platform_auth
from shared.auth import is_ctf_organizer, is_ctf_participant

logger = logging.getLogger(__name__)
IDENTITY_PLATFORM_ENROLLMENT_SESSION_KEY = "identity_platform_enrollment"
IDENTITY_PLATFORM_SIGNIN_SESSION_KEY = "identity_platform_signin"


def home(request):
    """Landing page - coming soon."""
    return render(request, "coming_soon.html")


def _clear_identity_platform_sessions(request) -> None:
    request.session.pop(IDENTITY_PLATFORM_ENROLLMENT_SESSION_KEY, None)
    request.session.pop(IDENTITY_PLATFORM_SIGNIN_SESSION_KEY, None)


def _render_identity_platform_login(request, *, status_code: int = 200, error_message: str = ""):
    return render(
        request,
        "identity_platform_login.html",
        {
            "error_message": error_message,
            "pending_enrollment": request.session.get(IDENTITY_PLATFORM_ENROLLMENT_SESSION_KEY),
            "pending_signin": request.session.get(IDENTITY_PLATFORM_SIGNIN_SESSION_KEY),
            "allowed_email_domain": getattr(settings, "IDENTITY_ALLOWED_EMAIL_DOMAIN", "paloaltonetworks.com"),
        },
        status=status_code,
    )


def _identity_platform_complete_login(request, *, id_token: str):
    user = identity_platform_auth.login_with_identity_token(request, id_token)
    login(request, user, backend="config.identity_platform.IdentityPlatformBackend")
    _clear_identity_platform_sessions(request)
    return HttpResponseRedirect(reverse("dashboard_router"))


def _handle_identity_platform_password_signin(request):
    email = request.POST.get("email", "").strip().lower()
    password = request.POST.get("password", "")
    if not email or not password:
        return _render_identity_platform_login(
            request,
            status_code=400,
            error_message="Email and password are required.",
        )

    try:
        sign_in_result = identity_platform_auth.sign_in_with_password(email, password)
    except identity_platform_auth.IdentityPlatformMFARequired as exc:
        request.session[IDENTITY_PLATFORM_SIGNIN_SESSION_KEY] = {
            "pending_credential": exc.pending_credential,
            "enrollment_id": exc.enrollment_id,
            "display_name": exc.display_name,
        }
        request.session.pop(IDENTITY_PLATFORM_ENROLLMENT_SESSION_KEY, None)
        request.session.save()
        return _render_identity_platform_login(request)
    except identity_platform_auth.IdentityPlatformAuthError as exc:
        return _render_identity_platform_login(request, status_code=403, error_message=str(exc))

    if not identity_platform_auth.is_allowed_identity_email(email):
        _clear_identity_platform_sessions(request)
        return _render_identity_platform_login(
            request,
            status_code=403,
            error_message=f"Only @{settings.IDENTITY_ALLOWED_EMAIL_DOMAIN} users may use corporate login.",
        )

    if sign_in_result.get("mfaInfo"):
        request.session[IDENTITY_PLATFORM_SIGNIN_SESSION_KEY] = {
            "pending_credential": sign_in_result["mfaPendingCredential"],
            "enrollment_id": sign_in_result["mfaInfo"][0]["mfaEnrollmentId"],
            "display_name": sign_in_result["mfaInfo"][0].get("displayName", ""),
        }
        request.session.pop(IDENTITY_PLATFORM_ENROLLMENT_SESSION_KEY, None)
        request.session.save()
        return _render_identity_platform_login(request)

    enrollment = identity_platform_auth.start_totp_enrollment(sign_in_result["idToken"], email)
    request.session[IDENTITY_PLATFORM_ENROLLMENT_SESSION_KEY] = {
        "email": email,
        "id_token": sign_in_result["idToken"],
        **enrollment,
    }
    request.session.pop(IDENTITY_PLATFORM_SIGNIN_SESSION_KEY, None)
    request.session.save()
    return _render_identity_platform_login(request)


def _handle_identity_platform_totp_enrollment(request):
    pending_enrollment = request.session.get(IDENTITY_PLATFORM_ENROLLMENT_SESSION_KEY)
    verification_code = request.POST.get("verification_code", "").strip()
    if not pending_enrollment:
        return _render_identity_platform_login(request, status_code=400, error_message="No MFA enrollment is pending.")
    if not verification_code:
        return _render_identity_platform_login(request, status_code=400, error_message="Verification code is required.")

    try:
        result = identity_platform_auth.finalize_totp_enrollment(
            id_token=pending_enrollment["id_token"],
            session_info=pending_enrollment["session_info"],
            verification_code=verification_code,
        )
    except identity_platform_auth.IdentityPlatformAuthError as exc:
        return _render_identity_platform_login(request, status_code=403, error_message=str(exc))

    return _identity_platform_complete_login(request, id_token=result["idToken"])


def _handle_identity_platform_totp_signin(request):
    pending_signin = request.session.get(IDENTITY_PLATFORM_SIGNIN_SESSION_KEY)
    verification_code = request.POST.get("verification_code", "").strip()
    if not pending_signin:
        return _render_identity_platform_login(
            request,
            status_code=400,
            error_message="No MFA sign-in challenge is pending.",
        )
    if not verification_code:
        return _render_identity_platform_login(request, status_code=400, error_message="Verification code is required.")

    try:
        result = identity_platform_auth.finalize_totp_sign_in(
            pending_credential=pending_signin["pending_credential"],
            enrollment_id=pending_signin["enrollment_id"],
            verification_code=verification_code,
        )
    except identity_platform_auth.IdentityPlatformAuthError as exc:
        return _render_identity_platform_login(request, status_code=403, error_message=str(exc))

    return _identity_platform_complete_login(request, id_token=result["idToken"])


def platform_login(request):
    """Route authentication to the configured provider."""
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse("dashboard_router"))

    if settings.AUTH_PROVIDER == "oidc":
        return HttpResponseRedirect(reverse("oidc_authentication_init"))
    if settings.AUTH_PROVIDER != "identity_platform":
        return HttpResponseForbidden("Unsupported auth provider")

    if request.method == "GET":
        return _render_identity_platform_login(request)

    action = request.POST.get("action", "").strip()
    if action == "password_sign_in":
        return _handle_identity_platform_password_signin(request)
    if action == "complete_totp_enrollment":
        return _handle_identity_platform_totp_enrollment(request)
    if action == "complete_totp_sign_in":
        return _handle_identity_platform_totp_signin(request)
    return _render_identity_platform_login(request, status_code=400, error_message="Unknown login action.")


@login_required
def dashboard_router(request):
    """Route authenticated users to the correct dashboard based on user type.

    - standard users -> Mission Control dashboard
    - ctf_organizer -> CTF Admin dashboard
    - ctf_participant -> Mission Control dashboard (with restricted nav)
    """
    if is_ctf_organizer(request.user):
        logger.debug("Routing organizer %s to Mission Control dashboard", request.user.email)
        return HttpResponseRedirect(reverse("mission_control:dashboard"))
    elif is_ctf_participant(request.user):
        logger.debug("Routing participant %s to Mission Control dashboard", request.user.email)
        return HttpResponseRedirect(reverse("mission_control:dashboard"))
    else:
        logger.debug("Routing standard user %s to Mission Control", request.user.email)
        return HttpResponseRedirect(reverse("mission_control:dashboard"))


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

    if "OIDCAuthenticationBackend" in backend:
        # Build the Cognito logout URL before clearing the session,
        # since provider_logout_url needs the request for the redirect URI.
        logout_url_method = getattr(settings, "OIDC_OP_LOGOUT_URL_METHOD", "")
        if logout_url_method:
            from django.utils.module_loading import import_string

            redirect_url = import_string(logout_url_method)(request)
        logger.debug("OIDC logout for %s", email)
    else:
        logger.debug("Session logout for %s", email)

    logout(request)
    return HttpResponseRedirect(redirect_url)
