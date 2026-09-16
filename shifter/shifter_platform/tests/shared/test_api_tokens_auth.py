"""Behavior tests for ApiToken DRF authentication and the audit seam (PLAT-102).

Covers the fail-closed semantics required by the preflight: a *bad* bearer token
is an authentication failure and must never fall through to a session, while
*no* bearer credential falls back to session auth. The audit seam is exercised
both as a monkeypatched spy (auth path) and end-to-end against a real AuditLog
row (seam path).
"""

from __future__ import annotations

import pytest
from rest_framework import exceptions
from rest_framework.test import APIRequestFactory

from shared.api_tokens import audit, scopes
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.api_tokens.models import ApiToken
from shared.audit import (
    AuditAction,
    AuditActorType,
)
from shared.models import AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="tokuser", password="x")


@pytest.fixture
def factory():
    return APIRequestFactory()


def _auth(factory, header: str | None):
    extra = {"HTTP_AUTHORIZATION": header} if header is not None else {}
    request = factory.get("/api/v1/risks/", **extra)
    return ApiTokenAuthentication().authenticate(request)


class TestNoTokenFallsBackToSession:
    def test_absent_authorization_returns_none(self, factory):
        assert _auth(factory, None) is None

    def test_non_bearer_scheme_returns_none(self, factory):
        # An unsupported authentication scheme is not ours; defer.
        assert _auth(factory, "Basic Zm9vOmJhcg==") is None


class TestValidToken:
    def test_authenticates_and_exposes_scopes(self, factory, user):
        token, raw = ApiToken.create_token(name="ci", created_by=user, scopes=[scopes.MISSION_CONTROL_RANGE_READ])
        result = _auth(factory, f"Bearer {raw}")
        assert result is not None
        auth_user, auth_token = result
        assert auth_user is None
        assert auth_token.pk == token.pk
        assert scopes.has_scope(auth_token.scopes, scopes.MISSION_CONTROL_RANGE_READ)

    def test_updates_last_used(self, factory, user):
        token, raw = ApiToken.create_token(name="ci", created_by=user, scopes=[scopes.MISSION_CONTROL_RANGE_READ])
        assert token.last_used_at is None
        _auth(factory, f"Bearer {raw}")
        token.refresh_from_db()
        assert token.last_used_at is not None


class TestBadTokenFailsClosed:
    def test_invalid_token_raises_and_audits(self, factory, user, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "shared.api_tokens.authentication.record_token_event",
            lambda *a, **k: calls.append((a, k)),
        )
        with pytest.raises(exceptions.AuthenticationFailed):
            _auth(factory, "Bearer shf_bogus.deadbeef")
        assert calls, "auth failure must be audited at the edge"
        # ...and specifically as an AUTH_FAILED event, not some other event type.
        event_arg = calls[0][0][0]
        assert event_arg == audit.TokenEvent.AUTH_FAILED

    def test_revoked_token_raises(self, factory, user):
        token, raw = ApiToken.create_token(name="ci", created_by=user, scopes=[scopes.MISSION_CONTROL_RANGE_READ])
        token.revoke()
        with pytest.raises(exceptions.AuthenticationFailed):
            _auth(factory, f"Bearer {raw}")

    def test_ctf_account_token_is_force_revoked_and_rejected(self, factory, django_user_model):
        """A token owned by a CTF-participant account is force-revoked and rejected.

        Fail-closed guard (shared/api_tokens/authentication.py): CTF/participant
        accounts must never authenticate via API tokens, and the attempt revokes
        the token as a side effect so a leaked token cannot be retried.
        """
        from management.services import get_user_profile

        owner = django_user_model.objects.create_user(username="ctfowner", password="x")
        profile = get_user_profile(owner)
        profile.user_type = "ctf_participant"
        profile.is_ctf_account = True
        profile.save()

        token, raw = ApiToken.create_token(name="ctf", created_by=owner, scopes=[scopes.MISSION_CONTROL_RANGE_READ])
        assert token.is_active is True

        with pytest.raises(exceptions.AuthenticationFailed):
            _auth(factory, f"Bearer {raw}")

        token.refresh_from_db()
        assert token.revoked_at is not None
        assert token.is_active is False

    def test_malformed_bearer_raises(self, factory):
        with pytest.raises(exceptions.AuthenticationFailed):
            _auth(factory, "Bearer")
        with pytest.raises(exceptions.AuthenticationFailed):
            _auth(factory, "Bearer one two")

    def test_authenticate_header_is_bearer(self, factory):
        request = factory.get("/api/v1/risks/")
        assert ApiTokenAuthentication().authenticate_header(request) == "Bearer"


class TestAuditSeam:
    def test_auth_failure_row_is_attributed_to_token_principal(self, factory):
        request = factory.get("/api/v1/risks/")
        before = AuditLog.objects.count()
        audit.record_token_event(audit.TokenEvent.AUTH_FAILED, request=request, context="bad token")
        assert AuditLog.objects.count() == before + 1
        row = AuditLog.objects.filter(action=AuditAction.LOGIN_FAILED).latest("timestamp")
        # A failed auth is the token principal's, not a user's.
        assert row.actor_type == AuditActorType.APIKEY
        assert row.actor_id is None

    def test_create_and_revoke_rows_are_attributed_to_acting_user(self):
        # Admin create/revoke pass the acting staff user's id; the row must read
        # as a USER action, not an API-key action.
        audit.record_token_event(audit.TokenEvent.CREATED, token_id="abc", token_pk=1, actor_id=7)
        audit.record_token_event(audit.TokenEvent.REVOKED, token_id="abc", token_pk=1, actor_id=7)
        created = AuditLog.objects.get(action=AuditAction.CREATE)
        revoked = AuditLog.objects.get(action=AuditAction.DELETE)
        assert created.actor_type == AuditActorType.USER
        assert created.actor_id == 7
        assert revoked.actor_type == AuditActorType.USER
        assert revoked.actor_id == 7
