"""Tests for the flag-aware dashboard router landing (#1369).

When the platform SPA is enabled the first authenticated screen is the SPA
home/dashboard at ``/``; when off, the legacy per-role routing is unchanged.
"""

from __future__ import annotations

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db

DASHBOARD_URL = "/dashboard/"


@pytest.fixture
def member(django_user_model):
    return django_user_model.objects.create_user(
        username="op",
        email="op@example.com",
        password="pw",
        is_staff=True,
    )


def test_dashboard_router_lands_on_spa_home_when_enabled(settings, member):
    settings.PLATFORM_SPA_ENABLED = True
    client = Client()
    client.force_login(member)
    resp = client.get(DASHBOARD_URL)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_dashboard_router_uses_legacy_routing_when_disabled(settings, member):
    settings.PLATFORM_SPA_ENABLED = False
    client = Client()
    client.force_login(member)
    resp = client.get(DASHBOARD_URL)
    assert resp.status_code == 302
    # Legacy behaviour routes to Mission Control, not the SPA root.
    assert resp.headers["Location"] != "/"
