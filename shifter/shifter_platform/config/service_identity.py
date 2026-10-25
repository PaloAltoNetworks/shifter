"""Google-native service ID-token verification at the composition boundary."""

from functools import partial

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from management.services import resolve_service_credential
from shared.credentials import CredentialContext


def _valid_service_subject(value: object) -> bool:
    """Return whether a Google service-account numeric identity is bounded."""
    return isinstance(value, str) and value.isascii() and value.isdecimal() and 10 <= len(value) <= 32


def _valid_service_email(value: object) -> bool:
    """Return whether claims identify a Google service-account address."""
    return isinstance(value, str) and value.endswith(".gserviceaccount.com")


def verify_service_credential(raw_token: str) -> CredentialContext:
    """Require exact Google proof, configured audience and explicit SQL admission."""
    audience = getattr(settings, "GCP_SERVICE_TOKEN_AUDIENCE", "")
    if not audience or not audience.startswith("https://"):
        raise ValueError("Service authentication unavailable")
    claims = id_token.verify_oauth2_token(raw_token, partial(Request(), timeout=10), audience=audience)
    subject = claims.get("sub")
    email = claims.get("email")
    trusted_claims = (
        claims.get("iss") == "https://accounts.google.com"
        and claims.get("aud") == audience
        and claims.get("email_verified") is True
    )
    if not trusted_claims or not _valid_service_subject(subject) or not _valid_service_email(email):
        raise ValueError("Service authentication denied")
    assert isinstance(subject, str)
    return resolve_service_credential(issuer=claims["iss"], subject=subject, audience=audience)
