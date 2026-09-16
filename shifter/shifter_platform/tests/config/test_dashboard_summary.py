"""Tests for the SPA dashboard summary read (#1369).

The dashboard summary is a bounded, cross-app composition of existing readable
facts. It requires authentication and fails closed on dependency errors.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

SUMMARY_URL = "/api/v1/dashboard/summary/"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="op",
        email="op@example.com",
        password="pw",
        is_staff=True,
    )


def _seed_range(user, *, status="ready"):
    """Seed a real Mission Control ``RangeInstance`` so ``get_active_range``
    returns a real ``RangeContext`` for ``user``.

    Drives the dashboard read through the real ``cms.services`` facade instead of
    patching the first-party service to return an impossible shape (#995). A
    malformed ``status`` exercises CMS's real projection-failure path at the
    persistence boundary.
    """
    from uuid import uuid4

    from cms.models import RangeInstance
    from cms.models import Request as CMSRequest
    from shared.enums import RangeSource, RequestType
    from workspaces.services import resolve_personal_workspace

    workspace_id = resolve_personal_workspace(user).workspace_id
    request = CMSRequest.objects.create(
        workspace_id=workspace_id,
        request_id=uuid4(),
        request_type=RequestType.RANGE.value,
        user=user,
    )
    return RangeInstance.objects.create(
        workspace_id=workspace_id,
        request=request,
        scenario_id="basic",
        user_id=user.id,
        status=status,
        range_source=RangeSource.MISSION_CONTROL.value,
        range_spec={"instances": [{"uuid": str(uuid4()), "name": "kali", "role": "attacker", "os_type": "kali"}]},
    )


def test_anonymous_is_401():
    assert APIClient().get(SUMMARY_URL).status_code == 401


def test_returns_bounded_summary_shape(user):
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(SUMMARY_URL).json()
    assert set(body) == {"active_range", "active_event"}
    assert set(body["active_range"]) == {"present", "status"}
    assert set(body["active_event"]) == {"present", "name"}


def test_no_active_range_or_event_by_default(user):
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(SUMMARY_URL).json()
    assert body["active_range"]["present"] is False
    assert body["active_event"]["present"] is False


# --- Positive ("present"/true) branches ---------------------------------------


def test_active_range_reported_when_present(user):
    """A real ready range projects the bounded present/status summary, driven
    through the real ``cms.services.get_active_range`` facade (#995)."""
    _seed_range(user, status="ready")
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(SUMMARY_URL).json()
    assert body["active_range"] == {"present": True, "status": "ready"}


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


def test_active_range_fails_closed_on_error(user):
    """A malformed persisted status makes real ``RangeContext`` construction
    raise; the dashboard summary fails closed to the bounded empty shape.

    Driven at the real persistence boundary rather than by patching the
    first-party ``get_active_range`` service (#995).
    """
    _seed_range(user, status="not-a-status")
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
