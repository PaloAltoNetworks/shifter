"""Behavioral coverage for provider assurance, not merely MFA enrollment."""

import time
from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from config import identity_platform


@pytest.mark.django_db
def test_enrolled_factor_without_second_factor_sign_in_cannot_create_session(monkeypatch, settings):
    settings.IDENTITY_PLATFORM_PROJECT_ID = "synthetic-project"
    settings.IDENTITY_ALLOWED_EMAIL_DOMAIN = "example.test"
    settings.IDENTITY_PLATFORM_API_KEY = "synthetic-public-api-key"
    claims = {
        "iss": "https://securetoken.google.com/synthetic-project",
        "aud": "synthetic-project",
        "sub": "synthetic-human",
        "email": "human@example.test",
        "email_verified": True,
        "auth_time": int(time.time()),
        "firebase": {"sign_in_provider": "password"},
    }
    monkeypatch.setattr(identity_platform.firebase_admin, "get_app", lambda: object())
    monkeypatch.setattr(identity_platform.firebase_auth, "verify_id_token", lambda *args, **kwargs: claims)
    monkeypatch.setattr(
        identity_platform.requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            ok=True,
            json=lambda: {"users": [{"emailVerified": True, "mfaInfo": [{"mfaEnrollmentId": "enrolled"}]}]},
        ),
    )
    with pytest.raises(identity_platform.IdentityPlatformMFAEnrollmentRequired):
        identity_platform.login_with_identity_token(RequestFactory().post("/login/"), "provider-proof")


@pytest.mark.parametrize(
    "substitution",
    [
        {"aud": "other-project"},
        {"iss": "https://accounts.google.com"},
        {"firebase": {"tenant": "other-tenant", "sign_in_second_factor": "totp"}},
    ],
)
def test_human_proof_must_match_project_issuer_and_tenant(substitution, monkeypatch, settings):
    settings.IDENTITY_PLATFORM_PROJECT_ID = "synthetic-project"
    settings.IDENTITY_PLATFORM_TENANT_ID = ""
    claims = {"aud": "synthetic-project", "iss": "https://securetoken.google.com/synthetic-project", "firebase": {}}
    monkeypatch.setattr(identity_platform.firebase_admin, "get_app", lambda: object())
    monkeypatch.setattr(
        identity_platform.firebase_auth, "verify_id_token", lambda *args, **kwargs: {**claims, **substitution}
    )
    with pytest.raises(identity_platform.IdentityPlatformAuthError):
        identity_platform.verify_identity_token("native-proof")
