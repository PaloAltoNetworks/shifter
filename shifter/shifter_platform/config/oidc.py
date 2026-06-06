"""OIDC utilities for Cognito integration."""

import logging
import os
import re
from urllib.parse import urlencode
from uuid import UUID

from django.contrib.auth.models import Group
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from config.bootstrap_admin import apply_bootstrap_admin_flags
from management.services import get_user_profile, update_cognito_sub
from risk_register.models import AuditLog
from risk_register.services import AuthPrincipal, audit_auth_event
from shared.auth import CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP

logger = logging.getLogger(__name__)

# Valid CTF user types that can be set from Cognito claims
VALID_CTF_USER_TYPES = {"standard", "ctf_organizer", "ctf_participant"}

# Django's UnicodeUsernameValidator pattern
DJANGO_USERNAME_PATTERN = re.compile(r"^[\w.@+-]+$")
DJANGO_USERNAME_MAX_LENGTH = 150


def generate_username(email: str) -> str:
    """Use email as username instead of default sha1 hash.

    mozilla-django-oidc defaults to base64(sha1(email)) for privacy
    (usernames are often public). For this internal tool, readable
    emails in admin/logs/queries are more useful than hash obfuscation.

    Raises:
        ValueError: If email exceeds Django's 150 char limit or contains
            characters not allowed in Django usernames. This indicates a
            mismatch between Cognito's allowed emails and Django's constraints
            that must be fixed at the source (Lambda allow-list).
    """
    if len(email) > DJANGO_USERNAME_MAX_LENGTH:
        logger.error(
            "OIDC username rejected: email exceeds %d chars (got %d): %s",
            DJANGO_USERNAME_MAX_LENGTH,
            len(email),
            email[:50] + "...",
        )
        raise ValueError(
            f"Email exceeds Django username limit of {DJANGO_USERNAME_MAX_LENGTH} characters. "
            "Fix the Cognito pre-signup Lambda allow-list."
        )

    if not DJANGO_USERNAME_PATTERN.match(email):
        logger.error(
            "OIDC username rejected: email contains invalid characters: %s",
            email,
        )
        raise ValueError(
            "Email contains characters not allowed in Django usernames. Fix the Cognito pre-signup Lambda allow-list."
        )

    return email


def provider_logout_url(request):
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
    """Custom OIDC backend that stores Cognito sub and CTF user type in UserProfile.

    The Cognito `sub` is the stable identifier for a user across tokens.
    We store it in UserProfile to enable MCP server lookups by sub
    (access tokens only contain sub, not email).

    CTF-specific claims:
    - custom:user_type: Sets the user's role (standard, ctf_organizer, ctf_participant)
    - custom:ctf_event_id: Sets the active CTF event for participant users
    """

    def create_user(self, claims):
        """Create user and populate cognito_sub and user_type from claims."""
        user = super().create_user(claims)
        apply_bootstrap_admin_flags(user, claims.get("email") or user.email)
        self._update_cognito_sub(user, claims)
        self._update_user_type(user, claims)

        # Audit log: new user created via OIDC
        cognito_sub = claims.get("sub", "")
        audit_auth_event(
            action=AuditLog.Action.CREATE,
            principal=AuthPrincipal(user_id=user.id, email=user.email, cognito_sub=cognito_sub),
            context="User created via OIDC first login",
        )

        return user

    def update_user(self, user, claims):
        """Update user and ensure cognito_sub and user_type are set."""
        user = super().update_user(user, claims)
        apply_bootstrap_admin_flags(user, claims.get("email") or user.email)
        self._update_cognito_sub(user, claims)
        self._update_user_type(user, claims)
        return user

    def authenticate(self, request, **kwargs):
        """Authenticate and log the event."""
        user = super().authenticate(request, **kwargs)

        # Get request context for audit logging
        source_ip = None
        user_agent = ""
        if request:
            xff = request.META.get("HTTP_X_FORWARDED_FOR")
            source_ip = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
            user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]

        if user:
            # Successful authentication
            audit_auth_event(
                action=AuditLog.Action.LOGIN,
                principal=AuthPrincipal(
                    user_id=user.id,
                    email=user.email,
                    cognito_sub=(getattr(user, "userprofile", None) and getattr(user.userprofile, "cognito_sub", ""))
                    or "",
                ),
                source_ip=source_ip,
                user_agent=user_agent,
            )
        else:
            # Failed authentication - log without user details
            # Note: We can't get email here as auth failed
            audit_auth_event(
                action=AuditLog.Action.LOGIN_FAILED,
                source_ip=source_ip,
                user_agent=user_agent,
                context="OIDC authentication failed",
            )

        return user

    def _update_cognito_sub(self, user, claims):
        """Store Cognito sub in user's profile."""
        cognito_sub = claims.get("sub")
        if not cognito_sub:
            logger.warning("OIDC claims missing 'sub' for user %s", user.email)
            return

        update_cognito_sub(user, cognito_sub)

    def _update_user_type(self, user, claims):
        """Update CTF groups and active CTF event from Cognito custom claims.

        Reads custom:user_type and custom:ctf_event_id from OIDC claims
        and adds/removes the user from the appropriate Django Groups.
        """
        user_type = claims.get("custom:user_type")

        CLAIM_TO_GROUP = {
            "ctf_organizer": CTF_ORGANIZER_GROUP,
            "ctf_participant": CTF_PARTICIPANT_GROUP,
        }

        if user_type and user_type in VALID_CTF_USER_TYPES:
            group_name = CLAIM_TO_GROUP.get(user_type)
            if group_name:
                group, _ = Group.objects.get_or_create(name=group_name)
                user.groups.add(group)
                logger.info(
                    "Added user %s to group '%s' from OIDC claim",
                    user.email,
                    group_name,
                )
            elif user_type == "standard":
                # Remove CTF groups for standard users
                ctf_groups = Group.objects.filter(name__in=[CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP])
                user.groups.remove(*ctf_groups)
                logger.info(
                    "Removed CTF groups for standard user %s from OIDC claim",
                    user.email,
                )

            # Keep user_type field in sync for backwards compat
            profile = get_user_profile(user)
            if profile.user_type != user_type:
                profile.user_type = user_type
                profile.save(update_fields=["user_type"])
        elif user_type:
            logger.warning(
                "Invalid user_type claim '%s' for user %s, ignoring",
                user_type,
                user.email,
            )

        # Set active CTF event for participant users
        ctf_event_id = claims.get("custom:ctf_event_id")
        is_participant = user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()
        if ctf_event_id and is_participant:
            try:
                event_uuid = UUID(ctf_event_id)
                from ctf.models import CTFEvent

                event = CTFEvent.objects.filter(pk=event_uuid).first()
                if event:
                    from management.services import set_active_ctf_event

                    set_active_ctf_event(user, event.pk)
                    logger.info(
                        "Set active CTF event %s for user %s",
                        ctf_event_id,
                        user.email,
                    )
                else:
                    logger.warning(
                        "CTF event %s not found for user %s",
                        ctf_event_id,
                        user.email,
                    )
            except (ValueError, TypeError):
                logger.warning(
                    "Invalid ctf_event_id claim '%s' for user %s, ignoring",
                    ctf_event_id,
                    user.email,
                )
