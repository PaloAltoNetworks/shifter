"""Personal token secrets belong exclusively to Knox."""

from datetime import timedelta

import pytest
from django.utils import timezone

from shared.api_tokens.models import ApiToken


@pytest.mark.django_db
def test_valid_personal_proof_without_live_grant_is_rejected(django_user_model, monkeypatch):
    from rest_framework.exceptions import AuthenticationFailed
    from rest_framework.test import APIRequestFactory

    from shared.api_tokens.authentication import ApiTokenAuthentication
    from shared.authorization import port

    user = django_user_model.objects.create_user(username="grant-revoked")
    _, raw = ApiToken.create_token(name="bounded", created_by=user, scopes=["ctf:event:read"])
    monkeypatch.setattr(port, "_provider_factory", None)
    request = APIRequestFactory().get("/api/v1/bootstrap/", HTTP_AUTHORIZATION=f"Bearer {raw}")
    with pytest.raises(AuthenticationFailed):
        ApiTokenAuthentication().authenticate(request)


@pytest.mark.django_db
def test_personal_token_has_finite_library_owned_credential(django_user_model):
    user = django_user_model.objects.create_user(username="personal-owner")
    token, raw = ApiToken.create_token(name="automation", created_by=user, scopes=["ctf:event:read"])
    assert token.expires_at is not None
    assert token.expires_at > timezone.now()
    assert token.knox_token_id
    from knox.auth import TokenAuthentication

    owner, native_token = TokenAuthentication().authenticate_credentials(raw.encode())
    assert owner == user
    assert native_token.pk == token.knox_token_id
    assert ApiToken.authenticate(raw) == token


@pytest.mark.django_db
def test_credential_scope_and_expiry_cannot_be_widened_after_issue(django_user_model):
    user = django_user_model.objects.create_user(username="immutable-owner")
    token, _ = ApiToken.create_token(name="bounded", created_by=user, scopes=["ctf:event:read"])
    token.scopes = ["ctf:event:write"]
    with pytest.raises(ValueError):
        token.save(update_fields=["scopes"])
    token.refresh_from_db()
    token.expires_at += timedelta(days=1)
    with pytest.raises(ValueError):
        token.save(update_fields=["expires_at"])


@pytest.mark.django_db
def test_historical_metadata_requires_reissue_and_cannot_authenticate(django_user_model):
    from uuid import uuid4

    user = django_user_model.objects.create_user(username="historical-owner")
    historical = ApiToken.objects.create(
        name="Historical",
        token_id=uuid4().hex,
        verifier_hash="0" * 64,
        created_by=user,
        principal_uuid=user.identity_principal.uuid,
        scopes=["ctf:event:read"],
    )
    assert historical.requires_reissue
    assert not historical.is_active
    assert ApiToken.authenticate(f"shf_{historical.token_id}.retired-proof") is None
    historical.revoke()
    assert not historical.requires_reissue
