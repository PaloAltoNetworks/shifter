"""Identity Platform authentication utilities for GCP deployments."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import firebase_admin
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from firebase_admin import auth as firebase_auth

from management.services import get_user_profile, update_cognito_sub
from risk_register.models import AuditLog
from risk_register.services import audit_auth_event
from shared.auth import CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP

logger = logging.getLogger(__name__)

User = get_user_model()

IDENTITY_PLATFORM_BASE_URL = "https://identitytoolkit.googleapis.com"
IDENTITY_PLATFORM_PASSWORD_SIGNIN_PATH = "/v1/accounts:signInWithPassword"
IDENTITY_PLATFORM_PASSWORD_RESET_PATH = "/v1/accounts:sendOobCode"
IDENTITY_PLATFORM_MFA_ENROLLMENT_START_PATH = "/v2/accounts/mfaEnrollment:start"
IDENTITY_PLATFORM_MFA_ENROLLMENT_FINALIZE_PATH = "/v2/accounts/mfaEnrollment:finalize"
IDENTITY_PLATFORM_MFA_SIGNIN_FINALIZE_PATH = "/v2/accounts/mfaSignIn:finalize"


class IdentityPlatformAuthError(RuntimeError):
    """Base failure for Identity Platform authentication problems."""


class IdentityPlatformSignInError(IdentityPlatformAuthError):
    """Credential sign-in failed."""


class IdentityPlatformMFARequired(IdentityPlatformAuthError):
    """Credential sign-in needs a second factor."""

    def __init__(self, pending_credential: str, enrollment_id: str, display_name: str = "") -> None:
        super().__init__("Multi-factor authentication is required")
        self.pending_credential = pending_credential
        self.enrollment_id = enrollment_id
        self.display_name = display_name


class IdentityPlatformEnrollmentRequired(IdentityPlatformAuthError):
    """Credential sign-in succeeded but the user must enroll TOTP."""

    def __init__(
        self,
        *,
        email: str,
        id_token: str,
        session_info: str,
        shared_secret_key: str,
        verification_code_length: int,
        hashing_algorithm: str,
        period_sec: int,
        otpauth_uri: str,
    ) -> None:
        super().__init__("Multi-factor enrollment is required")
        self.email = email
        self.id_token = id_token
        self.session_info = session_info
        self.shared_secret_key = shared_secret_key
        self.verification_code_length = verification_code_length
        self.hashing_algorithm = hashing_algorithm
        self.period_sec = period_sec
        self.otpauth_uri = otpauth_uri


def build_totp_provisioning_uri(
    *,
    email: str,
    shared_secret_key: str,
    hashing_algorithm: str,
    digits: int,
    period_sec: int,
    issuer: str,
) -> str:
    """Build a standards-compliant otpauth URI for authenticator apps."""
    label = f"{quote(issuer, safe='')}:{quote(email, safe='')}"
    query = urlencode(
        {
            "secret": shared_secret_key,
            "issuer": issuer,
            "algorithm": hashing_algorithm,
            "digits": str(digits),
            "period": str(period_sec),
        }
    )
    return f"otpauth://totp/{label}?{query}"


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
    raise IdentityPlatformSignInError(error_message)


def _allowed_email_domain() -> str:
    return getattr(settings, "IDENTITY_ALLOWED_EMAIL_DOMAIN", "paloaltonetworks.com").strip().lower()


def is_allowed_identity_email(email: str) -> bool:
    """Return True when the email belongs to the configured corporate domain."""
    domain = _allowed_email_domain()
    return bool(email) and email.lower().endswith(f"@{domain}")


def _apply_bootstrap_admin_flags(user: Any, email: str) -> None:
    """Apply env-configured bootstrap admin flags to the matching user."""
    normalized_email = email.strip().lower()
    is_superuser = normalized_email in getattr(settings, "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS", [])
    is_staff = is_superuser or normalized_email in getattr(settings, "PLATFORM_BOOTSTRAP_STAFF_EMAILS", [])

    updates: list[str] = []
    if user.is_staff != is_staff:
        user.is_staff = is_staff
        updates.append("is_staff")
    if user.is_superuser != is_superuser:
        user.is_superuser = is_superuser
        updates.append("is_superuser")

    if updates:
        user.save(update_fields=updates)


def sign_in_with_password(email: str, password: str) -> dict[str, Any]:
    """Authenticate against Identity Platform's password endpoint."""
    payload = _post_identity_request(
        IDENTITY_PLATFORM_PASSWORD_SIGNIN_PATH,
        {
            "email": email,
            "password": password,
            "returnSecureToken": True,
        },
    )

    if payload.get("mfaPendingCredential") and payload.get("mfaInfo"):
        enrollment = payload["mfaInfo"][0]
        raise IdentityPlatformMFARequired(
            pending_credential=payload["mfaPendingCredential"],
            enrollment_id=enrollment["mfaEnrollmentId"],
            display_name=enrollment.get("displayName", ""),
        )

    return payload


def start_totp_enrollment(id_token: str, email: str) -> dict[str, Any]:
    """Start TOTP enrollment for a signed-in user and return the secret metadata."""
    payload = _post_identity_request(
        IDENTITY_PLATFORM_MFA_ENROLLMENT_START_PATH,
        {
            "idToken": id_token,
            "totpEnrollmentInfo": {},
        },
    )
    session_info = payload["totpSessionInfo"]
    shared_secret_key = session_info["sharedSecretKey"]
    verification_code_length = int(session_info["verificationCodeLength"])
    hashing_algorithm = session_info["hashingAlgorithm"]
    period_sec = int(session_info["periodSec"])

    return {
        "session_info": session_info["sessionInfo"],
        "shared_secret_key": shared_secret_key,
        "verification_code_length": verification_code_length,
        "hashing_algorithm": hashing_algorithm,
        "period_sec": period_sec,
        "otpauth_uri": build_totp_provisioning_uri(
            email=email,
            shared_secret_key=shared_secret_key,
            hashing_algorithm=hashing_algorithm,
            digits=verification_code_length,
            period_sec=period_sec,
            issuer=getattr(settings, "IDENTITY_PLATFORM_ISSUER", "Shifter"),
        ),
    }


def finalize_totp_enrollment(*, id_token: str, session_info: str, verification_code: str) -> dict[str, Any]:
    """Complete TOTP enrollment and return the refreshed tokens."""
    return _post_identity_request(
        IDENTITY_PLATFORM_MFA_ENROLLMENT_FINALIZE_PATH,
        {
            "idToken": id_token,
            "displayName": getattr(settings, "IDENTITY_PLATFORM_TOTP_DISPLAY_NAME", "Shifter Authenticator"),
            "totpVerificationInfo": {
                "sessionInfo": session_info,
                "verificationCode": verification_code,
            },
        },
    )


def finalize_totp_sign_in(*, pending_credential: str, enrollment_id: str, verification_code: str) -> dict[str, Any]:
    """Complete the TOTP sign-in challenge and return tokens."""
    return _post_identity_request(
        IDENTITY_PLATFORM_MFA_SIGNIN_FINALIZE_PATH,
        {
            "mfaPendingCredential": pending_credential,
            "mfaEnrollmentId": enrollment_id,
            "totpVerificationInfo": {
                "verificationCode": verification_code,
            },
        },
    )


def send_password_reset_email(email: str) -> dict[str, Any]:
    """Trigger Identity Platform's password-reset email flow."""
    return _post_identity_request(
        IDENTITY_PLATFORM_PASSWORD_RESET_PATH,
        {
            "requestType": "PASSWORD_RESET",
            "email": email,
        },
    )


def verify_identity_token(id_token: str) -> dict[str, Any]:
    """Verify the Identity Platform ID token using Firebase Admin SDK."""
    _ensure_firebase_app()
    try:
        return firebase_auth.verify_id_token(id_token, check_revoked=True)
    except Exception as exc:  # pragma: no cover - firebase_admin exception tree is broad
        raise IdentityPlatformAuthError("Unable to verify Identity Platform token") from exc


def _sync_user_type_from_claims(user: Any, claims: dict[str, Any]) -> None:
    """Keep the profile user_type aligned with custom claims when present."""
    claim_user_type = claims.get("user_type") or claims.get("custom:user_type")
    if claim_user_type not in {"standard", "ctf_organizer", "ctf_participant", None}:
        return

    profile = get_user_profile(user)
    if claim_user_type and profile.user_type != claim_user_type:
        profile.user_type = claim_user_type
        profile.save(update_fields=["user_type"])

    # Keep the existing group semantics available if future custom claims are used.
    if claim_user_type == "standard":
        user.groups.remove(*user.groups.filter(name__in=[CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP]))


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


class IdentityPlatformBackend(BaseBackend):
    """Authenticate Django users from verified Identity Platform claims."""

    def authenticate(self, request, *, identity_claims: dict[str, Any] | None = None):
        if identity_claims is None:
            return None

        claims = IdentityUserClaims.from_mapping(identity_claims)
        if not claims.email_verified:
            raise IdentityPlatformAuthError("Identity Platform user email is not verified")
        if not is_allowed_identity_email(claims.email):
            raise IdentityPlatformAuthError(
                f"Only @{_allowed_email_domain()} users may log in through the corporate portal"
            )

        user, created = User.objects.get_or_create(
            username=claims.email,
            defaults={"email": claims.email, "is_active": True},
        )
        if not user.email:
            user.email = claims.email
            user.save(update_fields=["email"])

        _apply_bootstrap_admin_flags(user, claims.email)
        update_cognito_sub(user, claims.sub)
        _sync_user_type_from_claims(user, identity_claims)

        audit_auth_event(
            action=AuditLog.Action.CREATE if created else AuditLog.Action.LOGIN,
            user_id=user.id,
            email=user.email,
            cognito_sub=claims.sub,
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


def login_with_identity_token(request, id_token: str):
    """Verify the Identity Platform token and authenticate the Django user."""
    claims = verify_identity_token(id_token)
    backend = IdentityPlatformBackend()
    user = backend.authenticate(request, identity_claims=claims)
    if user is None:
        raise IdentityPlatformAuthError("Identity Platform login did not return a user")
    return user
