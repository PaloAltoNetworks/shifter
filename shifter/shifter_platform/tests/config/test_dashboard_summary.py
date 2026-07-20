"""Tests for the SPA dashboard summary read (#1369).

The dashboard summary is a bounded, cross-app composition of existing readable
facts. It requires authentication, fails closed on any dependency error, and
gates the risk-register load behind the same advisory access check the shell
uses. Authorization stays with the underlying resource endpoints.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from management.services import get_user_profile

pytestmark = pytest.mark.django_db

SUMMARY_URL = "/api/v1/dashboard/summary/"
ALLOWED_GROUPS = ["security"]


@pytest.fixture(autouse=True)
def _allowed_groups(settings):
    settings.RISK_REGISTER_ALLOWED_COGNITO_GROUPS = ALLOWED_GROUPS


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="op",
        email="op@example.com",
        password="pw",
        is_staff=True,
    )


def _grant_risk_access(user):
    profile = get_user_profile(user)
    profile.cognito_groups = list(ALLOWED_GROUPS)
    profile.save(update_fields=["cognito_groups"])


def test_anonymous_is_401():
    assert APIClient().get(SUMMARY_URL).status_code == 401


def test_returns_bounded_summary_shape(user):
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(SUMMARY_URL).json()
    assert set(body) == {"active_range", "active_event", "risk_register"}
    assert set(body["active_range"]) == {"present", "status"}
    assert set(body["active_event"]) == {"present", "name"}
    assert set(body["risk_register"]) == {"accessible", "open_count"}


def test_no_active_range_or_event_by_default(user):
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(SUMMARY_URL).json()
    assert body["active_range"]["present"] is False
    assert body["active_event"]["present"] is False


def test_risk_register_load_gated_by_access(user):
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(SUMMARY_URL).json()
    assert body["risk_register"]["accessible"] is False
    assert body["risk_register"]["open_count"] is None


def test_risk_register_load_reported_when_accessible(user):
    _grant_risk_access(user)
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(SUMMARY_URL).json()
    assert body["risk_register"]["accessible"] is True
    assert isinstance(body["risk_register"]["open_count"], int)


# --- Positive ("present"/true) branches ---------------------------------------


def test_active_range_reported_when_present(user, monkeypatch):
    monkeypatch.setattr("cms.services.get_active_range", lambda _u: SimpleNamespace(status="running"))
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(SUMMARY_URL).json()
    assert body["active_range"] == {"present": True, "status": "running"}


def test_active_event_reported_when_present(user, monkeypatch):
    monkeypatch.setattr(
        "ctf.bridges.get_user_role",
        lambda _u: SimpleNamespace(active_ctf_event=SimpleNamespace(name="DEF CON")),
    )
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(SUMMARY_URL).json()
    assert body["active_event"] == {"present": True, "name": "DEF CON"}


# --- Fail-closed (except) branches --------------------------------------------


def test_active_range_fails_closed_on_error(user, monkeypatch):
    def _boom(_u):
        raise RuntimeError("range backend down")

    monkeypatch.setattr("cms.services.get_active_range", _boom)
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(SUMMARY_URL)
    assert resp.status_code == 200
    assert resp.json()["active_range"] == {"present": False, "status": None}


def test_active_event_fails_closed_on_error(user, monkeypatch):
    def _boom(_u):
        raise RuntimeError("ctf backend down")

    monkeypatch.setattr("ctf.bridges.get_user_role", _boom)
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(SUMMARY_URL)
    assert resp.status_code == 200
    assert resp.json()["active_event"] == {"present": False, "name": None}


def test_risk_register_fails_closed_on_error(user, monkeypatch):
    _grant_risk_access(user)

    class _BoomManager:
        def filter(self, *args, **kwargs):
            raise RuntimeError("db down")

    monkeypatch.setattr("risk_register.models.Risk.objects", _BoomManager())
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(SUMMARY_URL)
    assert resp.status_code == 200
    # Access is granted, but the count fails closed to None rather than 500.
    assert resp.json()["risk_register"] == {"accessible": True, "open_count": None}
