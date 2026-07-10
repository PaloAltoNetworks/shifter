"""Tests for the ApiToken Django-admin management surface (PLAT-102).

Covers the requirement's "generation and revocation via the admin UI": creation
shows the raw token exactly once (server-side, never via the messages/cookie
framework), revocation works, lifecycle audit rows attribute the acting staff
user, the lifetime cap is enforced on every mutation path, and the raw secret
never leaks into list/search surfaces.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.contrib.admin import site
from django.contrib.messages import get_messages
from django.test import RequestFactory
from django.utils import timezone

from risk_register.models import AuditLog
from shared.api_tokens import scopes
from shared.api_tokens.admin import ApiTokenAdmin, ApiTokenForm
from shared.api_tokens.models import ApiToken

pytestmark = pytest.mark.django_db

ADD_URL = "/admin/shared/apitoken/add/"
LIST_URL = "/admin/shared/apitoken/"


@pytest.fixture
def superuser(django_user_model):
    return django_user_model.objects.create_superuser(
        username="root",
        email="root@example.com",
        password="pw",
    )


@pytest.fixture
def admin_client(client, superuser):
    client.force_login(superuser)
    return client


class TestAdminCreate:
    def test_create_renders_raw_token_once_server_side(self, admin_client, superuser):
        resp = admin_client.post(ADD_URL, {"name": "ci", "scopes": '["risk:read"]'})
        # Raw token is rendered server-side (200), not redirected with a message.
        assert resp.status_code == 200
        assert ApiToken.objects.count() == 1
        token = ApiToken.objects.get()
        assert token.scopes == [scopes.RISK_READ]

        body = resp.content.decode()
        # The FULL raw bearer (shf_<token_id>.<secret>) must be rendered, not just
        # the public display prefix — and it must actually authenticate.
        match = re.search(r"shf_[\w-]+\.[\w-]+", body)
        assert match is not None, "raw bearer token not rendered"
        resolved = ApiToken.authenticate(match.group())
        assert resolved is not None and resolved.pk == token.pk
        assert token.verifier_hash not in body  # ...never the stored verifier.

        # The secret must NOT be routed through the messages/cookie framework.
        assert not list(get_messages(resp.wsgi_request))
        assert "shf_" not in str(resp.cookies)

    def test_create_audits_with_staff_user_actor(self, admin_client, superuser):
        admin_client.post(ADD_URL, {"name": "ci", "scopes": '["risk:read"]'})
        row = AuditLog.objects.filter(action=AuditLog.Action.CREATE).latest("timestamp")
        assert row.actor_type == AuditLog.ActorType.USER
        assert row.actor_id == superuser.id

    def test_form_rejects_invalid_scope(self):
        form = ApiTokenForm(data={"name": "bad", "scopes": '["nope:nope"]'})
        assert not form.is_valid()
        assert "scopes" in form.errors

    def test_form_defaults_expiry_to_bounded_lifetime(self):
        form = ApiTokenForm(data={"name": "ci", "scopes": '["risk:read"]'})
        assert form.is_valid(), form.errors
        assert form.cleaned_data["expires_at"] is not None

    def test_form_rejects_expiry_beyond_ceiling(self, settings):
        settings.API_TOKEN_MAX_TTL_DAYS = 30
        far = (timezone.now() + timedelta(days=90)).isoformat()
        form = ApiTokenForm(data={"name": "ci", "scopes": '["risk:read"]', "expires_at": far})
        assert not form.is_valid()
        assert "expires_at" in form.errors


class TestChangePathTtlCap:
    def test_editing_expiry_beyond_ceiling_is_rejected(self, settings, django_user_model):
        settings.API_TOKEN_MAX_TTL_DAYS = 30
        owner = django_user_model.objects.create_user(username="o", password="pw")
        token, _ = ApiToken.create_token(name="t", created_by=owner, scopes=[scopes.RISK_READ])
        far = (timezone.now() + timedelta(days=365)).isoformat()
        # The SAME form governs the change path, so the cap cannot be bypassed.
        form = ApiTokenForm(
            data={"name": token.name, "scopes": '["risk:read"]', "expires_at": far},
            instance=token,
        )
        assert not form.is_valid()
        assert "expires_at" in form.errors


class TestAdminRevoke:
    def test_revoke_action_revokes_and_audits_with_staff_actor(self, admin_client, superuser, django_user_model):
        owner = django_user_model.objects.create_user(username="o", password="pw")
        token, _ = ApiToken.create_token(name="t", created_by=owner, scopes=[scopes.RISK_READ])
        resp = admin_client.post(
            LIST_URL,
            {"action": "revoke_tokens", "_selected_action": [str(token.pk)]},
        )
        assert resp.status_code == 302
        token.refresh_from_db()
        assert token.revoked_at is not None
        row = AuditLog.objects.filter(action=AuditLog.Action.DELETE).latest("timestamp")
        assert row.actor_type == AuditLog.ActorType.USER
        assert row.actor_id == superuser.id


class TestNoHardDelete:
    def test_delete_is_disabled_so_revocation_cannot_be_bypassed(self, admin_client, django_user_model):
        owner = django_user_model.objects.create_user(username="o", password="pw")
        token, _ = ApiToken.create_token(name="t", created_by=owner, scopes=[scopes.RISK_READ])

        admin = ApiTokenAdmin(ApiToken, site)
        request = RequestFactory().get(LIST_URL)
        assert admin.has_delete_permission(request) is False
        # Disabling delete permission also removes the bulk "delete selected" action.
        assert "delete_selected" not in admin.get_actions(request)

        # The hard-delete view is forbidden; the row survives for audit/lifecycle.
        resp = admin_client.post(f"/admin/shared/apitoken/{token.pk}/delete/")
        assert resp.status_code in (403, 302)
        assert ApiToken.objects.filter(pk=token.pk).exists()


class TestNoSecretLeak:
    def test_verifier_not_in_list_display_or_search(self):
        assert "verifier_hash" not in ApiTokenAdmin.list_display
        assert "verifier_hash" not in getattr(ApiTokenAdmin, "search_fields", ())
