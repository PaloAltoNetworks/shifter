"""Behavior tests for the ApiToken model (PLAT-102).

Drives the real model against real rows: token creation, the non-reversible
verifier, lifecycle (revoke/expire), scope validation, and coalesced
``last_used_at`` writes.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="tokuser", password="x")


class TestCreateToken:
    def test_returns_instance_and_raw_token(self, user):
        token, raw = ApiToken.create_token(name="ci", created_by=user, scopes=[scopes.RISK_READ])
        assert isinstance(token, ApiToken)
        assert raw.startswith("shf_")
        # The raw secret is never persisted in any readable form.
        assert raw not in (token.verifier_hash, token.token_id)
        assert token.verifier_hash != raw
        assert token.scopes == [scopes.RISK_READ]
        assert token.display_id == f"shf_{token.token_id}"
        assert token.display_id != raw

    def test_normalizes_scopes(self, user):
        token, _ = ApiToken.create_token(
            name="ci",
            created_by=user,
            scopes=[scopes.RISK_WRITE, scopes.RISK_READ, scopes.RISK_WRITE],
        )
        assert token.scopes == [scopes.RISK_READ, scopes.RISK_WRITE]

    def test_rejects_invalid_scopes(self, user):
        with pytest.raises(scopes.InvalidScopeError):
            ApiToken.create_token(name="bad", created_by=user, scopes=["nope:nope"])
        assert ApiToken.objects.count() == 0

    def test_token_ids_are_unique_across_tokens(self, user):
        _, raw1 = ApiToken.create_token(name="a", created_by=user, scopes=[scopes.RISK_READ])
        _, raw2 = ApiToken.create_token(name="b", created_by=user, scopes=[scopes.RISK_READ])
        assert raw1 != raw2
        assert ApiToken.objects.count() == 2


class TestAuthenticate:
    def test_valid_token_authenticates(self, user):
        token, raw = ApiToken.create_token(name="ci", created_by=user, scopes=[scopes.RISK_READ])
        resolved = ApiToken.authenticate(raw)
        assert resolved is not None
        assert resolved.pk == token.pk

    def test_wrong_secret_is_rejected(self, user):
        token, _ = ApiToken.create_token(name="ci", created_by=user, scopes=[scopes.RISK_READ])
        forged = f"shf_{token.token_id}.deadbeefdeadbeef"
        assert ApiToken.authenticate(forged) is None

    def test_unknown_token_id_is_rejected(self, user):
        assert ApiToken.authenticate("shf_doesnotexist.whatever") is None

    def test_malformed_token_is_rejected(self, user):
        assert ApiToken.authenticate("") is None
        assert ApiToken.authenticate("nope") is None
        assert ApiToken.authenticate("shf_onlyid") is None

    def test_revoked_token_is_rejected(self, user):
        token, raw = ApiToken.create_token(name="ci", created_by=user, scopes=[scopes.RISK_READ])
        token.revoke()
        assert token.is_active is False
        assert ApiToken.authenticate(raw) is None

    def test_expired_token_is_rejected(self, user):
        token, raw = ApiToken.create_token(
            name="ci",
            created_by=user,
            scopes=[scopes.RISK_READ],
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        assert token.is_active is False
        assert ApiToken.authenticate(raw) is None


class TestTouchLastUsedCoalescing:
    def test_first_touch_writes_then_coalesces(self, user):
        token, _ = ApiToken.create_token(name="ci", created_by=user, scopes=[scopes.RISK_READ])
        assert token.last_used_at is None

        assert token.touch_last_used(coalesce_seconds=300) is True
        first = token.last_used_at
        assert first is not None

        # A second touch within the window must NOT write (avoids amplification).
        assert token.touch_last_used(coalesce_seconds=300) is False
        token.refresh_from_db()
        assert token.last_used_at == first

    def test_touch_writes_again_after_window(self, user):
        token, _ = ApiToken.create_token(name="ci", created_by=user, scopes=[scopes.RISK_READ])
        token.touch_last_used(coalesce_seconds=300)
        # Backdate beyond the window.
        ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now() - timedelta(seconds=600))
        token.refresh_from_db()
        assert token.touch_last_used(coalesce_seconds=300) is True
