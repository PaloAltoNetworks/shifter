"""End-to-end STRIDE validation parity on the Risk create/update API (#1302).

Before this change only the read serializer validated STRIDE codes, so the
create and update endpoints silently persisted invalid categories. These tests
exercise the real DRF surface to lock the parity in.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from risk_register.models import Risk

from .conftest import grant_risk_register_access

pytestmark = pytest.mark.django_db

RISKS_URL = "/api/v1/risks/"


@pytest.fixture
def staff(django_user_model):
    user = django_user_model.objects.create_user(
        username="staff",
        email="staff@example.com",
        password="pw",
        is_staff=True,
    )
    grant_risk_register_access(user)
    return user


@pytest.fixture
def client(staff):
    api = APIClient()
    api.force_authenticate(user=staff)
    return api


def _details(response):
    return response.json().get("error", {}).get("details", {})


def test_create_rejects_invalid_stride(client):
    resp = client.post(
        RISKS_URL,
        {"title": "t", "description": "d", "stride_categories": ["X"]},
        format="json",
    )
    assert resp.status_code == 400
    assert "stride_categories" in _details(resp)
    assert not Risk.all_objects.exists()


def test_create_accepts_valid_stride(client):
    resp = client.post(
        RISKS_URL,
        {"title": "t", "description": "d", "stride_categories": ["S", "T"]},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["stride_categories"] == ["S", "T"]


def test_update_rejects_invalid_stride(client):
    created = client.post(
        RISKS_URL,
        {"title": "t", "description": "d", "stride_categories": ["S"]},
        format="json",
    )
    risk_id = created.json()["id"]
    resp = client.patch(
        f"{RISKS_URL}{risk_id}/",
        {"stride_categories": ["nope"]},
        format="json",
    )
    assert resp.status_code == 400
    assert "stride_categories" in _details(resp)
    # The invalid update did not persist.
    assert Risk.objects.get(pk=risk_id).stride_categories == ["S"]
