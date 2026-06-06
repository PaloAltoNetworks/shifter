"""Identity Platform authentication utilities for GCP deployments."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import firebase_admin
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.http import HttpRequest
from firebase_admin import auth as firebase_auth

from config.bootstrap_admin import apply_bootstrap_admin_flags
from management.services import get_user_profile, update_cognito_sub
from risk_register.models import AuditLog
from risk_register.services import AuthPrincipal, audit_auth_event
from shared.auth import CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP

logger = logging.getLogger(__name__)

User = get_user_model()

IDENTITY_PLATFORM_BASE_URL = "https://identitytoolkit.googleapis.com"
IDENTITY_PLATFORM_ACCOUNT_LOOKUP_PATH = "/v1/accounts:lookup"


class IdentityPlatformAuthError(RuntimeError):
    """Base failure for Identity Platform authentication problems."""

    code = "identity_platform_auth_failed"


class IdentityPlatformEmailVerificationRequired(IdentityPlatformAuthError):
    """Identity Platform email must be verified before the app creates a session."""

    code = "email_verification_required"


class IdentityPlatformMFAEnrollmentRequired(IdentityPlatformAuthError):
    """Identity Platform account must have an enrolled second factor before session creation."""

    code = "mfa_enrollment_required"


@dataclass(frozen=True)
class IdentityUserClaims:
    """Normalized claims used by the Django backend."""

    sub: str
    email: str
    email_verified: bool

    @classmethod
    def from_mapping(cls, claims: dict[str, Any]) -> IdentityUserClaims:
        try:
            sub = str(claims["sub"])
            email = str(claims["email"])
        except KeyError as exc:
            raise IdentityPlatformAuthError("Identity token is missing required claims") from exc

        email_verified = bool(claims.get("email_verified"))
        return cls(sub=sub, email=email, email_verified=email_verified)


def _ensure_firebase_app() -> firebase_admin.App:
    """Return a singleton Firebase Admin app using ADC/Workload Identity."""
    try:
        return firebase_admin.get_app()
    except ValueError:
        options: dict[str, str] = {}
        if getattr(settings, "IDENTITY_PLATFORM_PROJECT_ID", ""):
            options["projectId"] = settings.IDENTITY_PLATFORM_PROJECT_ID
        return firebase_admin.initialize_app(options=options or None)


def _identity_api_key() -> str:
    api_key = getattr(settings, "IDENTITY_PLATFORM_API_KEY", "")
    if not api_key:
        raise IdentityPlatformAuthError("Identity Platform API key is not configured")
    return api_key


def _identity_endpoint(path: str) -> str:
    return f"{IDENTITY_PLATFORM_BASE_URL}{path}?key={_identity_api_key()}"


def _post_identity_request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        _identity_endpoint(path),
        json=payload,
        timeout=15,
    )
    try:
        body = response.json()
    except ValueError as exc:
        raise IdentityPlatformAuthError(f"Identity Platform returned non-JSON response: {response.text}") from exc

    if response.ok:
        return body

    error_message = body.get("error", {}).get("message", "Identity Platform request failed")
    raise IdentityPlatformAuthError(error_message)


def _lookup_identity_account(*, id_token: str) -> dict[str, Any]:
    payload = _post_identity_request(IDENTITY_PLATFORM_ACCOUNT_LOOKUP_PATH, {"idToken": id_token})
    users = payload.get("users", [])
    if not users:
        raise IdentityPlatformAuthError("Identity Platform lookup returned no user record")
    return users[0]


def _allowed_email_domain() -> str:
    return getattr(settings, "IDENTITY_ALLOWED_EMAIL_DOMAIN", "paloaltonetworks.com").strip().lower()


def _allowed_emails() -> set[str]:
    return {email.strip().lower() for email in getattr(settings, "IDENTITY_ALLOWED_EMAILS", []) if email.strip()}


def is_allowed_identity_email(email: str) -> bool:
    """Return True when the email belongs to the configured corporate allow-list."""
    normalized = email.strip().lower()
    if not normalized:
        return False
    if normalized in _allowed_emails():
        return True
    return normalized.endswith(f"@{_allowed_email_domain()}")


def identity_platform_client_config() -> dict[str, Any]:
    """Return the browser-side Identity Platform configuration."""
    project_id = getattr(settings, "IDENTITY_PLATFORM_PROJECT_ID", "")
    auth_domain = getattr(settings, "IDENTITY_PLATFORM_AUTH_DOMAIN", "").strip()
    if not auth_domain and project_id:
        auth_domain = f"{project_id}.firebaseapp.com"

    return {
        "apiKey": _identity_api_key(),
        "authDomain": auth_domain,
        "projectId": project_id,
        "allowedEmailDomain": _allowed_email_domain(),
        "allowedEmails": sorted(_allowed_emails()),
        "issuer": getattr(settings, "IDENTITY_PLATFORM_ISSUER", "Shifter"),
        "totpDisplayName": getattr(settings, "IDENTITY_PLATFORM_TOTP_DISPLAY_NAME", "Shifter Authenticator"),
    }


def verify_identity_token(id_token: str) -> dict[str, Any]:
    """Verify the Identity Platform ID token using Firebase Admin SDK."""
    _ensure_firebase_app()
    try:
        return firebase_auth.verify_id_token(id_token, check_revoked=True)
    except Exception as exc:  # pragma: no cover - firebase_admin exception tree is broad
        raise IdentityPlatformAuthError("Unable to verify Identity Platform token") from exc


def _assert_account_can_create_app_session(*, id_token: str, claims: IdentityUserClaims) -> None:
    if not claims.email_verified:
        raise IdentityPlatformEmailVerificationRequired("Corporate login requires a verified email address.")

    account = _lookup_identity_account(id_token=id_token)
    if not account.get("emailVerified"):
        raise IdentityPlatformEmailVerificationRequired("Corporate login requires a verified email address.")
    if not account.get("mfaInfo"):
        raise IdentityPlatformMFAEnrollmentRequired("Corporate login requires an enrolled multi-factor authenticator.")


def _sync_user_type_from_claims(user: Any, claims: dict[str, Any]) -> None:
    """Keep the profile user_type aligned with custom claims when present."""
    claim_user_type = claims.get("user_type") or claims.get("custom:user_type")
    if claim_user_type not in {"standard", "ctf_organizer", "ctf_participant", None}:
        return

    profile = get_user_profile(user)
    if claim_user_type and profile.user_type != claim_user_type:
        profile.user_type = claim_user_type
        profile.save(update_fields=["user_type"])

    if claim_user_type == "standard":
        user.groups.remove(*user.groups.filter(name__in=[CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP]))


class IdentityPlatformBackend(BaseBackend):
    """Authenticate Django users from verified Identity Platform claims."""

    def authenticate(self, request: HttpRequest | None, **kwargs: Any):
        identity_claims = kwargs.get("identity_claims")
        if identity_claims is None:
            return None

        claims = IdentityUserClaims.from_mapping(identity_claims)
        if not claims.email_verified:
            raise IdentityPlatformEmailVerificationRequired("Identity Platform user email is not verified")
        if not is_allowed_identity_email(claims.email):
            raise IdentityPlatformAuthError(
                f"Only corporate users from @{_allowed_email_domain()} may log in through the portal"
            )

        user, created = User.objects.get_or_create(
            username=claims.email,
            defaults={"email": claims.email, "is_active": True},
        )
        if not user.email:
            user.email = claims.email
            user.save(update_fields=["email"])

        apply_bootstrap_admin_flags(user, claims.email)
        update_cognito_sub(user, claims.sub)
        _sync_user_type_from_claims(user, identity_claims)

        audit_auth_event(
            action=AuditLog.Action.CREATE if created else AuditLog.Action.LOGIN,
            principal=AuthPrincipal(user_id=user.id, email=user.email, cognito_sub=claims.sub),
            source_ip=(request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() if request else None)
            or (request.META.get("REMOTE_ADDR") if request else None),
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:500] if request else ""),
            context="Identity Platform login" if not created else "User created via Identity Platform first login",
        )

        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


def login_with_identity_token(request: HttpRequest | None, id_token: str):
    """Verify the Identity Platform token, enforce session gates, and authenticate the Django user."""
    claims_payload = verify_identity_token(id_token)
    claims = IdentityUserClaims.from_mapping(claims_payload)
    _assert_account_can_create_app_session(id_token=id_token, claims=claims)

    backend = IdentityPlatformBackend()
    user = backend.authenticate(request, identity_claims=claims_payload)
    if user is None:
        raise IdentityPlatformAuthError("Identity Platform login did not return a user")
    return user
