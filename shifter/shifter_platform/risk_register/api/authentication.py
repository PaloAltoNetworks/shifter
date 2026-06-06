"""API Key authentication backend for Django REST Framework."""

import logging

from rest_framework import authentication, exceptions

from risk_register.models import APIKey, AuditLog
from risk_register.services import AuditEvent, audit_log, get_client_ip

logger = logging.getLogger(__name__)


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    API Key authentication.

    Clients should authenticate by passing the API key in the X-API-Key header.
    Example: X-API-Key: rr_live_abc123...
    """

    keyword = "X-API-Key"

    def authenticate(self, request):
        """
        Authenticate the request and return a tuple of (user, auth) or None.

        For API key auth, we return (None, api_key) since there's no user.
        The API key is available via request.auth.
        """
        api_key = request.META.get(f"HTTP_{self.keyword.upper().replace('-', '_')}")

        if not api_key:
            return None  # Let other authenticators try

        authenticated_key = APIKey.authenticate(api_key)

        # Get request context for audit logging
        source_ip = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]
        endpoint = request.path

        if not authenticated_key:
            # Log failed authentication attempt
            # Extract prefix if possible for debugging
            key_prefix = api_key[:8] if api_key and len(api_key) >= 8 else "invalid"
            audit_log(
                AuditEvent(
                    entity_type=AuditLog.EntityType.APIKEY,
                    entity_id=0,
                    action=AuditLog.Action.LOGIN_FAILED,
                    actor_type=AuditLog.ActorType.APIKEY,
                    actor_id=None,
                    new_state={"key_prefix": key_prefix, "endpoint": endpoint},
                    context="Invalid or expired API key",
                    source_ip=source_ip,
                    user_agent=user_agent,
                )
            )
            raise exceptions.AuthenticationFailed("Invalid or expired API key")

        # Update last_used_at
        authenticated_key.update_last_used()

        # Log successful authentication
        audit_log(
            AuditEvent(
                entity_type=AuditLog.EntityType.APIKEY,
                entity_id=authenticated_key.id,
                action=AuditLog.Action.LOGIN,
                actor_type=AuditLog.ActorType.APIKEY,
                actor_id=authenticated_key.id,
                new_state={"key_prefix": authenticated_key.prefix, "endpoint": endpoint},
                source_ip=source_ip,
                user_agent=user_agent,
            )
        )

        # Return (user, auth) - user is None for API key auth
        # The api_key is accessible via request.auth
        return (None, authenticated_key)

    def authenticate_header(self, request):
        """Return a string to be used as the WWW-Authenticate header."""
        return self.keyword


class APIKeyOrSessionAuthentication(authentication.BaseAuthentication):
    """
    Combined authentication that accepts either API key or session.

    This is useful for views that should work for both UI and API access.
    """

    def authenticate(self, request):
        """Try API key first, then fall back to session."""
        # Try API key
        api_key_auth = APIKeyAuthentication()
        try:
            result = api_key_auth.authenticate(request)
            if result is not None:
                return result
        except exceptions.AuthenticationFailed:
            raise

        # Fall back to session authentication
        from rest_framework.authentication import SessionAuthentication

        session_auth = SessionAuthentication()
        return session_auth.authenticate(request)
