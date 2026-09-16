"""Identity Platform authentication utilities for GCP deployments."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import firebase_admin
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.db import transaction
from django.http import HttpRequest
from firebase_admin import auth as firebase_auth

from config.bootstrap_admin import apply_bootstrap_admin_flags
from config.cognito_groups import sync_cognito_groups_from_claims
from config.organizer_authority import reconcile_provider_privileged_groups
from config.user_type_sync import sync_user_type
from management.services import (
    BindingConflictError,
    BindOutcome,
    bind_provider_identity,
    resolve_user_by_provider_identity,
)
from shared.audit import (
    AuditAction,
    AuditActorType,
    AuditEntityType,
    AuditEvent,
    AuthPrincipal,
    audit_auth_event,
    audit_log,
    get_client_ip,
)
from shared.verified_identity import VerifiedIdentity

if TYPE_CHECKING:
    # Aliased to avoid clashing with the ``User = get_user_model()`` runtime
    # binding below while still annotating with the concrete user model type.
    from django.contrib.auth.models import User as DjangoUser

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


def _build_verified_identity(claims: dict[str, Any], *, source: str) -> VerifiedIdentity:
    """Build a strict VerifiedIdentity from a verified Identity Platform token payload.

    Translates the shared module's generic validation into Identity
    Platform's established error codes (issue #1521): a missing/blank
    issuer, subject, or email is a generic auth failure, while a missing or
    non-literal-True ``email_verified`` is the specific, already-classified
    :class:`IdentityPlatformEmailVerificationRequired` the client-facing view
    maps to a 403. Rejects before any user lookup, creation, or binding.

    ``bool(claims.get("email_verified"))`` is not valid here because the
    string ``"false"`` becomes ``True``.
    """
    issuer = claims.get("iss")
    subject = claims.get("sub")
    email = claims.get("email")
    if (
        not isinstance(issuer, str)
        or not issuer.strip()
        or not isinstance(subject, str)
        or not subject.strip()
        or not isinstance(email, str)
        or not email.strip()
    ):
        raise IdentityPlatformAuthError("Identity token is missing required claims")

    if claims.get("email_verified") is not True:
        raise IdentityPlatformEmailVerificationRequired("Identity Platform user email is not verified")

    return VerifiedIdentity(issuer=issuer, subject=subject, email=email, email_verified=True, source=source)


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
    """Return the configured Identity Platform API key, raising if it is unset."""
    api_key = getattr(settings, "IDENTITY_PLATFORM_API_KEY", "")
    if not api_key:
        raise IdentityPlatformAuthError("Identity Platform API key is not configured")
    return api_key


def _identity_endpoint(path: str) -> str:
    """Build the Identity Platform REST endpoint URL for ``path`` with the API key."""
    return f"{IDENTITY_PLATFORM_BASE_URL}{path}?key={_identity_api_key()}"


def _post_identity_request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST ``payload`` to an Identity Platform endpoint and return the parsed JSON body."""
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
    """Return the Identity Platform account record for ``id_token`` (raises if none)."""
    payload = _post_identity_request(IDENTITY_PLATFORM_ACCOUNT_LOOKUP_PATH, {"idToken": id_token})
    users = payload.get("users", [])
    if not users:
        raise IdentityPlatformAuthError("Identity Platform lookup returned no user record")
    return users[0]


def _allowed_email_domain() -> str:
    """Return the configured corporate email domain, lowercased."""
    return getattr(settings, "IDENTITY_ALLOWED_EMAIL_DOMAIN", "paloaltonetworks.com").strip().lower()


def _allowed_emails() -> set[str]:
    """Return the configured per-address email allow-list, lowercased."""
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

    # The approved email domain and per-address allow-list are policy/PII
    # projections and are deliberately NOT exposed to the anonymous browser
    # (issue #1920). Email admission stays authoritative server-side in
    # ``is_allowed_identity_email``/``IdentityPlatformBackend`` and at
    # registration in the provider ``beforeCreate`` hook.
    return {
        "apiKey": _identity_api_key(),
        "authDomain": auth_domain,
        "projectId": project_id,
        "issuer": getattr(settings, "IDENTITY_PLATFORM_ISSUER", "Shifter"),
        "totpDisplayName": getattr(settings, "IDENTITY_PLATFORM_TOTP_DISPLAY_NAME", "Shifter Authenticator"),
    }


def verify_identity_token(id_token: str) -> dict[str, Any]:
    """Verify the Identity Platform ID token using Firebase Admin SDK."""
    _ensure_firebase_app()
    try:
        return firebase_auth.verify_id_token(id_token, check_revoked=True)
    except Exception as exc:
        # firebase_admin's exception tree is broad; normalize any verification
        # failure to our single auth error type so callers handle one thing.
        raise IdentityPlatformAuthError("Unable to verify Identity Platform token") from exc


def _assert_account_can_create_app_session(id_token: str) -> None:
    """Raise unless the Identity Platform account may start an app session.

    The caller's ``VerifiedIdentity`` already guarantees ``email_verified is
    True`` from the token claims; this independently re-checks the account
    record's ``emailVerified`` value via a fresh Identity Platform REST
    lookup (a second, independent provider-state check, issue #1521) plus
    enrolled MFA.
    """
    account = _lookup_identity_account(id_token=id_token)
    if account.get("emailVerified") is not True:
        raise IdentityPlatformEmailVerificationRequired("Corporate login requires a verified email address.")
    if not account.get("mfaInfo"):
        raise IdentityPlatformMFAEnrollmentRequired("Corporate login requires an enrolled multi-factor authenticator.")


def _sync_user_type_from_claims(
    user: DjangoUser,
    claims: dict[str, Any],
    request: HttpRequest | None = None,
) -> None:
    """Align CTF group membership and profile user_type from Identity claims.

    Delegates to the shared, audited :func:`config.user_type_sync.sync_user_type`
    so Identity Platform, OIDC, and dev-login share one mapping and one
    fail-closed audit trail (issue #937 SEC-5).
    """
    claim_user_type = claims.get("user_type") or claims.get("custom:user_type")
    sync_user_type(user, claim_user_type, source="identity_platform", request=request)


def _request_audit_context(request: HttpRequest | None) -> tuple[str | None, str]:
    """Return ``(source_ip, user_agent)`` for audit logging, tolerating a missing request."""
    if request is None:
        return None, ""
    source_ip = get_client_ip(request)
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]
    return source_ip, user_agent


def _resolve_identity_platform_user(identity: VerifiedIdentity) -> DjangoUser | None:
    """Resolve the Django user for a verified identity, subject-first (issue #1521).

    Delegates the issuer/subject lookup to the canonical management persistence
    seam (:func:`management.services.resolve_user_by_provider_identity`,
    ADR-009-R6) so the resolution policy is not re-implemented per provider.
    Falls back to the historical username-by-email lookup only when it finds no
    bound/legacy match -- i.e. for an unbound/first-bootstrap account.
    ``bind_provider_identity`` is the single place that enforces
    bind-once/compare and never rebinds a drifted or colliding identity from
    here.
    """
    matched = resolve_user_by_provider_identity(identity.issuer, identity.subject).first()
    if matched is not None:
        return matched
    return User.objects.filter(username=identity.email, profile__is_ctf_account=False).first()


class IdentityPlatformBackend(BaseBackend):
    """Authenticate Django users from verified Identity Platform claims."""

    def authenticate(self, request: HttpRequest | None, **kwargs: Any) -> DjangoUser | None:
        identity_claims = kwargs.get("identity_claims")
        if identity_claims is None:
            return None

        identity = _build_verified_identity(identity_claims, source="identity_platform")
        if not is_allowed_identity_email(identity.email):
            raise IdentityPlatformAuthError(
                f"Only corporate users from @{_allowed_email_domain()} may log in through the portal"
            )

        # Resolution, first-login user creation / email persistence, binding,
        # elevation, and the strict audit are one atomic security mutation
        # (issue #1521): a binding conflict or strict-audit failure rolls back
        # the newly created user and any email write too, so no orphaned or
        # partially-mutated account survives a rejected login. _bind_and_elevate
        # translates BindingConflictError to IdentityPlatformAuthError, which
        # propagates out of the block and triggers the rollback.
        with transaction.atomic():
            user = _resolve_identity_platform_user(identity)
            if user is not None and not user.is_active:
                # A deactivated, suspended, or soft-deleted account (all
                # is_active=False) must not obtain a session, and bind/elevate
                # must never reactivate it as a side effect (PLAT-236, #1943).
                raise IdentityPlatformAuthError("This account is not permitted to sign in")
            created = user is None
            if user is None:
                user = User.objects.create_user(username=identity.email, email=identity.email, is_active=True)
            elif not user.email:
                user.email = identity.email
                user.save(update_fields=["email"])
            self._bind_and_elevate(user, identity)

        _sync_user_type_from_claims(user, identity_claims, request)
        sync_cognito_groups_from_claims(user, identity_claims, request)
        reconcile_provider_privileged_groups(user, identity_claims, request)

        source_ip, user_agent = _request_audit_context(request)
        audit_auth_event(
            action=AuditAction.CREATE if created else AuditAction.LOGIN,
            principal=AuthPrincipal(user_id=user.id, email=user.email, cognito_sub=identity.subject),
            source_ip=source_ip,
            user_agent=user_agent,
            context="Identity Platform login" if not created else "User created via Identity Platform first login",
        )

        from config.workspace_invitation_auth import attach_fresh_verified_identity

        attach_fresh_verified_identity(request, identity)

        return user

    def _bind_and_elevate(self, user: DjangoUser, identity: VerifiedIdentity) -> None:
        """Bind the verified identity and apply bootstrap flags as one security mutation.

        Binding, elevation, and their audit record run inside one
        ``transaction.atomic()`` so a failed audit/uniqueness check leaves no
        partial privilege state (issue #1521). A binding conflict is
        translated to :class:`IdentityPlatformAuthError` so the client sees
        the same generic auth-failure envelope as any other rejection.
        """
        try:
            with transaction.atomic():
                bind_outcome = bind_provider_identity(user, identity.issuer, identity.subject)
                updated_fields = apply_bootstrap_admin_flags(user, identity)
                if bind_outcome != BindOutcome.UNCHANGED or updated_fields:
                    audit_log(
                        AuditEvent(
                            entity_type=AuditEntityType.USER,
                            entity_id=user.id,
                            action=AuditAction.ROLE_SYNC,
                            actor_type=AuditActorType.SYSTEM,
                            new_state={"bind": bind_outcome.value, "updated_fields": updated_fields},
                            context="identity_platform verified-identity bind/elevate",
                        ),
                        strict=True,
                    )
        except BindingConflictError as exc:
            raise IdentityPlatformAuthError("Identity Platform identity binding conflict") from exc

    def get_user(self, user_id: int) -> DjangoUser | None:
        # Return no principal for an inactive account (PLAT-236, #1943) so a
        # deactivated/suspended/soft-deleted user cannot reload an existing
        # Identity Platform session.
        try:
            user = User.objects.select_related("profile").get(pk=user_id)
        except User.DoesNotExist:
            return None
        return user if user.is_active else None


def login_with_identity_token(request: HttpRequest | None, id_token: str) -> DjangoUser:
    """Verify the Identity Platform token, enforce session gates, and authenticate the Django user."""
    claims_payload = verify_identity_token(id_token)
    _build_verified_identity(claims_payload, source="identity_platform")
    _assert_account_can_create_app_session(id_token)

    backend = IdentityPlatformBackend()
    user = backend.authenticate(request, identity_claims=claims_payload)
    if user is None:
        raise IdentityPlatformAuthError("Identity Platform login did not return a user")
    return user
