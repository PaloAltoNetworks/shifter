"""Inactive-account authentication enforcement tests (PLAT-236, #1943).

Deactivated / suspended / soft-deleted accounts all hold ``is_active=False``,
the sole authentication-enforcement bit. These tests assert the paths the
preflight required to fail closed: provider session reload (``get_user``) and API
token authentication reject an inactive or soft-deleted owner.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.test import APIRequestFactory

from config.identity_platform import IdentityPlatformBackend
from config.oidc import ShifterOIDCBackend
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.api_tokens.models import ApiToken
from shared.api_tokens.scopes import MISSION_CONTROL_RANGE_READ

pytestmark = pytest.mark.django_db

User = get_user_model()


def _make_user(username: str, **kwargs) -> User:
    return User.objects.create_user(username=username, email=f"{username}@example.com", **kwargs)


class TestProviderSessionReload:
    def test_idp_get_user_none_for_inactive(self):
        user = _make_user("idp", is_active=False)
        assert IdentityPlatformBackend().get_user(user.id) is None

    def test_idp_get_user_returns_active(self):
        user = _make_user("idp2")
        assert IdentityPlatformBackend().get_user(user.id) == user

    def test_oidc_get_user_none_for_inactive(self):
        user = _make_user("oidc", is_active=False)
        assert ShifterOIDCBackend().get_user(user.id) is None

    def test_oidc_get_user_returns_active(self):
        user = _make_user("oidc2")
        assert ShifterOIDCBackend().get_user(user.id) == user


class TestTokenOwnerRejection:
    def _authenticate(self, raw_token: str):
        request = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return ApiTokenAuthentication().authenticate(request)

    def test_active_owner_authenticates(self):
        owner = _make_user("owner")
        _token, raw = ApiToken.create_token(name="t", scopes=[MISSION_CONTROL_RANGE_READ], created_by=owner)
        result = self._authenticate(raw)
        assert result is not None

    def test_inactive_owner_rejected(self):
        owner = _make_user("owner2", is_active=False)
        _token, raw = ApiToken.create_token(name="t", scopes=[MISSION_CONTROL_RANGE_READ], created_by=owner)
        with pytest.raises(exceptions.AuthenticationFailed):
            self._authenticate(raw)

    def test_soft_deleted_owner_rejected(self):
        owner = _make_user("owner3")
        owner.profile.deleted_at = timezone.now()
        owner.profile.save(update_fields=["deleted_at"])
        _token, raw = ApiToken.create_token(name="t", scopes=[MISSION_CONTROL_RANGE_READ], created_by=owner)
        with pytest.raises(exceptions.AuthenticationFailed):
            self._authenticate(raw)
