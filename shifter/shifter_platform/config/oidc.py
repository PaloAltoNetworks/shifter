"""OIDC utilities for Cognito integration."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousOperation
from django.db import transaction
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

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
from shared.verified_identity import VerifiedIdentity, VerifiedIdentityError

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def _email_verified_is_true(value: object) -> bool:
    """Return True only for a verified email, tolerant of provider encoding.

    AWS Cognito's UserInfo endpoint returns ``email_verified`` as the string
    ``"true"``/``"false"``, while the ID token returns a JSON boolean. Accept a
    boolean ``True`` or the string ``"true"`` (case-insensitive); reject
    ``False``, ``"false"``, ``None``, and anything else. Fail-closed: a
    non-verified or malformed value never counts as verified.
    """
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() == "true"


def provider_logout_url(request: HttpRequest) -> str:
    """Return Cognito logout URL to clear the identity provider session.

    Called by mozilla-django-oidc's OIDCLogoutView when OIDC_OP_LOGOUT_URL_METHOD
    is configured. Redirects to Cognito's /logout endpoint which clears the
    Cognito session cookie, then redirects back to our logout_uri.

    In local dev (no OIDC env vars), returns "/" to skip Cognito and go home.

    See: https://docs.aws.amazon.com/cognito/latest/developerguide/logout-endpoint.html
    """
    auth_domain = os.environ.get("OIDC_AUTH_DOMAIN", "")
    client_id = os.environ.get("OIDC_RP_CLIENT_ID", "")

    if not auth_domain or not client_id:
        # Local dev - just redirect home, no Cognito to log out of
        return "/"

    # Build the post-logout redirect URL
    scheme = "https" if request.is_secure() else "http"
    host = request.get_host()
    logout_uri = f"{scheme}://{host}/"

    params = urlencode(
        {
            "client_id": client_id,
            "logout_uri": logout_uri,
        }
    )

    return f"{auth_domain}/logout?{params}"


class ShifterOIDCBackend(OIDCAuthenticationBackend):
    """Custom OIDC backend that binds Cognito identity and CTF user type in UserProfile.

    The Cognito `sub` is the stable identifier for a user across tokens.
    We store it (with its issuer) in UserProfile to enable MCP server lookups
    by sub (access tokens only contain sub, not email).

    CTF-specific claims:
    - custom:user_type: Sets the user's role (standard, ctf_organizer, ctf_participant)
    - custom:ctf_event_id: Sets the active CTF event for participant users

    Issue #1521: a login may bind or change bootstrap-admin flags only after
    strict verification yields a non-empty issuer, subject, email, and the
    literal ``email_verified is True``; a bound account accepts only the same
    ``(issuer, subject)``. ``mozilla-django-oidc`` 5.0.2's base ``verify_token``
    decodes with ``verify_aud=False`` and is not given an expected issuer, and
    its base ``verify_claims`` only checks that an ``email`` claim is present,
    so this backend adds the missing Shifter deployment checks at the adapter
    boundary (``verify_token`` / ``verify_claims`` / ``filter_users_by_claims``)
    rather than trusting the base call alone.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Verified ID-token evidence stashed by verify_token during a real
        # authenticate() callback (issue #1521). None until verify_token runs;
        # every hook below fails closed when it is absent.
        self._verified_issuer: str | None = None
        self._verified_subject: str | None = None

    def get_user(self, user_id: int) -> Any:
        """Load the account-origin profile with the session user."""
        user_model = get_user_model()
        try:
            return user_model._default_manager.select_related("profile").get(pk=user_id)
        except user_model.DoesNotExist:
            return None

    def verify_token(self, token: str, **kwargs: Any) -> Any:
        """Validate the token signature, then assert issuer/audience/azp match this deployment.

        The base call only verifies the JWS and nonce; it does not check
        audience and is not given an expected issuer, so the persisted
        issuer/subject cannot be trusted from it alone (issue #1521). Stashes
        the verified ``iss`` / ``sub`` on the instance (same pattern as
        ``self._request`` in :meth:`authenticate`) so ``verify_claims``,
        ``filter_users_by_claims``, ``create_user``, and ``update_user`` can
        build a :class:`~shared.verified_identity.VerifiedIdentity` from
        trusted evidence.
        """
        payload = super().verify_token(token, **kwargs)

        expected_issuer = getattr(settings, "OIDC_ISSUER_URL", "")
        issuer = payload.get("iss")
        if not expected_issuer or not issuer or issuer != expected_issuer:
            raise SuspiciousOperation("OIDC ID token issuer does not match the expected issuer")

        client_id = self.OIDC_RP_CLIENT_ID
        audience = payload.get("aud")
        audience_values = audience if isinstance(audience, list) else [audience]
        if client_id not in audience_values:
            raise SuspiciousOperation("OIDC ID token audience does not match the configured client")

        authorized_party = payload.get("azp")
        if authorized_party is not None and authorized_party != client_id:
            raise SuspiciousOperation("OIDC ID token authorized party does not match the configured client")

        subject = payload.get("sub")
        if not subject:
            raise SuspiciousOperation("OIDC ID token is missing a subject")

        self._verified_issuer = issuer
        self._verified_subject = subject
        return payload

    def verify_claims(self, claims: dict[str, Any]) -> bool:
        """Require present email/sub and a verified email.

        ``email_verified`` is accepted as boolean ``True`` or the string
        ``"true"`` (case-insensitive): AWS Cognito's UserInfo endpoint returns
        it as a string while the ID token returns a boolean. Anything else
        (``False``, ``"false"``, ``None``, absent) fails closed.

        Also requires the UserInfo ``sub`` to equal the already-verified
        ID-token ``sub`` (issue #1521): the UserInfo endpoint's response is
        not independently protocol-verified the way the ID token is.
        """
        if not super().verify_claims(claims):
            return False

        subject = claims.get("sub")
        email = claims.get("email")
        email_verified = claims.get("email_verified")
        if not subject or not email or not _email_verified_is_true(email_verified):
            return False

        verified_subject = self._verified_subject
        return bool(verified_subject) and subject == verified_subject

    def filter_users_by_claims(self, claims: dict[str, Any]) -> Any:
        """Resolve the account subject-first on the verified ID-token subject.

        Delegates the issuer/subject lookup to the canonical management
        persistence seam (:func:`management.services.resolve_user_by_provider_identity`,
        ADR-009-R6) so the identity-key query is not re-implemented per provider.
        Falls back to the base email lookup only when it finds no bound/legacy
        match -- i.e. for an unbound/first-bootstrap account.
        ``bind_provider_identity`` is the single place that enforces
        bind-once/compare and never rebinds a drifted or colliding identity from
        here (issue #1521).
        """
        subject = self._verified_subject
        issuer = self._verified_issuer
        if subject and issuer:
            matches = resolve_user_by_provider_identity(issuer, subject)
            if matches.exists():
                return matches
        return super().filter_users_by_claims(claims).exclude(profile__is_ctf_account=True)

    def create_user(self, claims: dict[str, Any]) -> User:
        """Create user and bind/elevate from verified identity evidence.

        User creation, binding, elevation, and the strict audit run inside one
        ``transaction.atomic()`` so a binding conflict or a strict-audit failure
        rolls the new user back too -- no orphaned account survives a rejected
        login (issue #1521). The claim-derived group/user-type sync and the
        best-effort login audit run only after the security mutation commits.
        """
        identity = self._verified_identity(claims)
        with transaction.atomic():
            user = super().create_user(claims)
            self._bind_and_elevate(user, identity)
        sync_cognito_groups_from_claims(user, claims, getattr(self, "_request", None))
        reconcile_provider_privileged_groups(user, claims, getattr(self, "_request", None))
        self._update_user_type(user, claims)

        # Audit log: new user created via OIDC
        audit_auth_event(
            action=AuditAction.CREATE,
            principal=AuthPrincipal(user_id=user.id, email=user.email, cognito_sub=identity.subject),
            context="User created via OIDC first login",
        )

        return user

    def update_user(self, user: User, claims: dict[str, Any]) -> User:
        """Update user and bind/elevate from verified identity evidence.

        The user update, binding, elevation, and strict audit run inside one
        ``transaction.atomic()`` so a binding conflict or strict-audit failure
        leaves no partial mutation on the existing account (issue #1521).
        """
        from management.services import is_temporary_ctf_account

        if is_temporary_ctf_account(user):
            raise SuspiciousOperation("Temporary CTF accounts cannot use platform authentication")
        identity = self._verified_identity(claims)
        with transaction.atomic():
            user = super().update_user(user, claims)
            self._bind_and_elevate(user, identity)
        sync_cognito_groups_from_claims(user, claims, getattr(self, "_request", None))
        reconcile_provider_privileged_groups(user, claims, getattr(self, "_request", None))
        self._update_user_type(user, claims)
        return user

    def authenticate(self, request: HttpRequest | None, **kwargs: Any) -> User | None:
        """Authenticate and log the event."""
        # Stash the request so create_user / update_user (whose signatures are
        # fixed by mozilla-django-oidc and omit the request) can attribute the
        # user-type sync audit row to the request context (issue #937 SEC-5).
        self._request = request

        # Get request context for audit logging up front, so it is available on
        # both the return-None and the raising failure paths below.
        source_ip = None
        user_agent = ""
        if request:
            source_ip = get_client_ip(request)
            user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]

        try:
            user = super().authenticate(request, **kwargs)
        except Exception as exc:
            # Token exchange, JWKS lookup, JWT/nonce/state validation, and
            # claims/user-creation errors raise here, before the ``user is None``
            # branch below. Audit them as a failed login with a *bounded* reason
            # — the exception type name only, never ``str(exc)``, which can carry
            # token endpoint URLs, response bodies, auth codes, or client ids —
            # then re-raise so mozilla-django-oidc's callback failure handling is
            # unchanged.
            audit_auth_event(
                action=AuditAction.LOGIN_FAILED,
                source_ip=source_ip,
                user_agent=user_agent,
                context=f"OIDC authentication error: {type(exc).__name__}",
            )
            raise

        if user:
            # Successful authentication
            audit_auth_event(
                action=AuditAction.LOGIN,
                principal=AuthPrincipal(
                    user_id=user.id,
                    email=user.email,
                    cognito_sub=(getattr(user, "userprofile", None) and getattr(user.userprofile, "cognito_sub", ""))
                    or "",
                ),
                source_ip=source_ip,
                user_agent=user_agent,
                context="OIDC callback login",
            )
        else:
            # Failed authentication - log without user details.
            # The backend returned None (no matching/valid user); we cannot get
            # the email here as auth failed.
            audit_auth_event(
                action=AuditAction.LOGIN_FAILED,
                source_ip=source_ip,
                user_agent=user_agent,
                context="OIDC authentication failed: no_user",
            )

        return user

    def _verified_identity(self, claims: dict[str, Any]) -> VerifiedIdentity:
        """Build the VerifiedIdentity from stashed verified ID-token evidence + claims.

        Raises before any user lookup/creation (issue #1521): called at the
        top of ``create_user`` / ``update_user``, before either calls into the
        mozilla base or the binding service.
        """
        issuer = self._verified_issuer
        subject = self._verified_subject
        if not issuer or not subject:
            raise SuspiciousOperation("OIDC verified issuer/subject unavailable for identity binding")

        # verify_claims already gated email/email_verified before any lookup;
        # narrow the untrusted claim values here so the strict VerifiedIdentity
        # contract (the sole validator) receives typed inputs. A non-str email
        # or non-literal-True email_verified fails closed via SuspiciousOperation
        # (mozilla-django-oidc's generic callback-failure path).
        email = claims.get("email")
        email_verified = claims.get("email_verified")
        if not isinstance(email, str) or not _email_verified_is_true(email_verified):
            raise SuspiciousOperation("OIDC verified email evidence unavailable for identity binding")

        try:
            return VerifiedIdentity(
                issuer=issuer,
                subject=subject,
                email=email,
                email_verified=True,
            )
        except VerifiedIdentityError as exc:
            raise SuspiciousOperation(str(exc)) from exc

    def _bind_and_elevate(self, user: User, identity: VerifiedIdentity) -> None:
        """Bind the verified identity and apply bootstrap flags as one security mutation.

        Binding, elevation, and their audit record run inside one
        ``transaction.atomic()`` so a failed audit/uniqueness check leaves no
        partial privilege state (issue #1521). A binding conflict is
        translated to ``SuspiciousOperation`` so it flows through
        mozilla-django-oidc's existing generic callback-failure path rather
        than surfacing as a raw exception.
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
                            context="oidc verified-identity bind/elevate",
                        ),
                        strict=True,
                    )
        except BindingConflictError as exc:
            raise SuspiciousOperation("OIDC identity binding conflict") from exc

    def _update_user_type(self, user: User, claims: dict[str, Any]) -> None:
        """Sync CTF groups, profile user_type, and active CTF event from claims.

        Delegates to the shared, audited :func:`config.user_type_sync.sync_user_type`
        so OIDC, Identity Platform, and dev-login share one mapping and one
        fail-closed audit trail (issue #937 SEC-5).
        """
        sync_user_type(
            user,
            claims.get("custom:user_type"),
            source="oidc",
            request=getattr(self, "_request", None),
            ctf_event_id=claims.get("custom:ctf_event_id"),
        )
