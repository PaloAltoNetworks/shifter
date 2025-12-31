"""API Key authentication backend for Django REST Framework."""

from rest_framework import authentication, exceptions

from risk_register.models import APIKey


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

        if not authenticated_key:
            raise exceptions.AuthenticationFailed("Invalid or expired API key")

        # Update last_used_at
        authenticated_key.update_last_used()

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
