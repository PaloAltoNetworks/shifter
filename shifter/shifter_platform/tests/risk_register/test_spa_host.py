"""Tests for the flag-gated Risk Register SPA host view + routing (#1302)."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import resolve

from risk_register import views

from .conftest import grant_risk_register_access

pytestmark = pytest.mark.django_db

LIST_URL = "/risk-register/"


@pytest.fixture
def member(django_user_model):
    user = django_user_model.objects.create_user(
        username="member",
        email="member@example.com",
        password="pw",
        is_staff=True,
    )
    grant_risk_register_access(user)
    return user


@pytest.fixture
def non_group_user(django_user_model):
    # Authenticated but deliberately NOT granted risk-register group access.
    return django_user_model.objects.create_user(
        username="outsider",
        email="outsider@example.com",
        password="pw",
        is_staff=True,
    )


@pytest.fixture
def spa_on(settings):
    settings.RISK_REGISTER_SPA_ENABLED = True


@pytest.fixture
def spa_off(settings):
    settings.RISK_REGISTER_SPA_ENABLED = False


class TestSpaEnabled:
    def test_list_serves_shell_and_primes_csrf(self, spa_on, member):
        client = Client()
        client.force_login(member)
        resp = client.get(LIST_URL)
        assert resp.status_code == 200
        assert b'id="root"' in resp.content
        assert "csrftoken" in resp.cookies

    def test_detail_deep_link_serves_shell(self, spa_on, member):
        client = Client()
        client.force_login(member)
        # Client-routed even for an id that does not exist server-side.
        resp = client.get("/risk-register/risks/999/")
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_client_router_catchall_serves_shell(self, spa_on, member):
        client = Client()
        client.force_login(member)
        resp = client.get("/risk-register/deep/client/route/")
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_anonymous_redirects_to_login(self, spa_on):
        resp = Client().get(LIST_URL)
        assert resp.status_code == 302

    def test_authenticated_non_group_user_still_gets_shell(self, spa_on, non_group_user):
        # Documented #1301 decision: the shell is served to any authenticated
        # user (group access is NOT enforced at the shell layer); the SPA renders
        # its own access-denied state from the authoritative API 403s. This test
        # locks that decision so a later "add a group check here" cannot silently
        # narrow access without failing.
        client = Client()
        client.force_login(non_group_user)
        resp = client.get(LIST_URL)
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_page_post_is_405(self, spa_on, member):
        client = Client()
        client.force_login(member)
        resp = client.post("/risk-register/risks/create/", {})
        assert resp.status_code == 405


class TestSpaDisabled:
    def test_list_serves_django_page_not_shell(self, spa_off, member):
        client = Client()
        client.force_login(member)
        resp = client.get(LIST_URL)
        assert resp.status_code == 200
        assert b'id="root"' not in resp.content

    def test_client_router_catchall_404s(self, spa_off, member):
        client = Client()
        client.force_login(member)
        resp = client.get("/risk-register/deep/client/route/")
        assert resp.status_code == 404


def test_action_routes_stay_django():
    assert resolve("/risk-register/risks/5/delete/").func is views.risk_delete
    assert resolve("/risk-register/risks/5/restore/").func is views.risk_restore
    assert resolve("/risk-register/risks/5/comments/add/").func is views.comment_add
