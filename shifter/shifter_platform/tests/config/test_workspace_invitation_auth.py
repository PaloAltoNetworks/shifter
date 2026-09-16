"""Fresh verified-identity handoff from both supported provider adapters."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import RequestFactory
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from config.identity_platform import IdentityPlatformBackend
from config.oidc import ShifterOIDCBackend
from shared.verified_identity import VerifiedIdentity

pytestmark = pytest.mark.django_db
_REQUEST_ATTRIBUTE = "_workspace_invitation_verified_identity"


def test_identity_platform_attaches_fresh_verified_identity_to_auth_request(settings):
    settings.IDENTITY_ALLOWED_EMAIL_DOMAIN = "example.com"
    request = RequestFactory().post("/auth/identity/session/")
    claims = {
        "iss": "https://securetoken.google.com/test-project",
        "sub": "invitation-identity-platform-subject",
        "email": "identity-platform-invitee@example.com",
        "email_verified": True,
    }

    user = IdentityPlatformBackend().authenticate(request, identity_claims=claims)

    assert user is not None
    identity = getattr(request, _REQUEST_ATTRIBUTE)
    assert isinstance(identity, VerifiedIdentity)
    assert identity.email == claims["email"]
    assert identity.subject == claims["sub"]
    assert identity.email_verified is True


def test_oidc_verified_claims_are_attached_only_after_successful_authentication(django_user_model, settings):
    settings.OIDC_ISSUER_URL = "https://issuer.example.test"
    user = django_user_model.objects.create_user(
        username="oidc-invitee@example.com",
        email="oidc-invitee@example.com",
    )
    request = RequestFactory().get("/oidc/callback/")
    backend = ShifterOIDCBackend()
    identity = VerifiedIdentity(
        issuer=settings.OIDC_ISSUER_URL,
        subject="invitation-oidc-subject",
        email=user.email,
        email_verified=True,
        source="oidc",
    )

    def provider_authenticate(*args, **kwargs):
        del args, kwargs
        backend._last_verified_identity = identity
        return user

    with patch.object(OIDCAuthenticationBackend, "authenticate", side_effect=provider_authenticate):
        result = backend.authenticate(request)

    assert result == user
    assert getattr(request, _REQUEST_ATTRIBUTE) == identity


def test_oidc_rejected_claims_do_not_stage_verified_identity(settings):
    settings.OIDC_ISSUER_URL = "https://issuer.example.test"
    backend = ShifterOIDCBackend()
    backend._verified_issuer = settings.OIDC_ISSUER_URL
    backend._verified_subject = "expected-subject"
    claims = {
        "sub": "different-subject",
        "email": "oidc-invitee@example.com",
        "email_verified": True,
    }

    with patch.object(OIDCAuthenticationBackend, "verify_claims", return_value=True):
        assert backend.verify_claims(claims) is False

    assert backend._last_verified_identity is None
