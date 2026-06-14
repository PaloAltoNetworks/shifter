"""Behavior tests for the Range API endpoints.

These tests drive the real Django URLs with a real database and assert
observable behavior: HTTP status, response JSON, and persisted ORM state
(Range rows, audit log rows). Range provisioning dispatches to ECS only when
configured; under the test settings it is unconfigured, so create/cancel/
destroy complete without any cloud call and no boundary mock is required.

Fixtures (windows_os, make_agent, hydratable_scenario, launch_range_via_api)
come from tests/mission_control/conftest.py; authenticated_client from the
root conftest.
"""

import json

import pytest
from django.test import Client
from django.urls import reverse

from engine.models import Range
from risk_register.models import AuditLog

pytestmark = pytest.mark.django_db


def _json(response):
    return json.loads(response.content)


# ---------------------------------------------------------------------------
# get_range
# ---------------------------------------------------------------------------


class TestGetRange:
    def test_requires_login(self):
        response = Client().get(reverse("mission_control:get_range"))
        assert response.status_code == 302

    def test_returns_no_range_when_none_exists(self, authenticated_client):
        client, _ = authenticated_client(email="norange@example.com")
        response = client.get(reverse("mission_control:get_range"))
        assert response.status_code == 200
        data = _json(response)
        assert data["has_range"] is False
        assert data["range"] is None
        assert data["connection_urls"] == []

    def test_returns_active_range_after_launch(self, authenticated_client, launch_range_via_api):
        client, user = authenticated_client(email="active@example.com")
        launch_resp, _agent, scenario_id = launch_range_via_api(client, user)
        assert launch_resp.status_code == 200

        response = client.get(reverse("mission_control:get_range"))
        assert response.status_code == 200
        data = _json(response)
        assert data["has_range"] is True
        assert data["range"]["scenario_id"] == scenario_id
        assert data["range"]["user_id"] == user.id
        # The persisted range is PENDING: create_range stores it and would move
        # it to PROVISIONING only once the ECS task starts, which the test
        # settings leave unconfigured.
        assert data["range"]["status"] == "pending"
        assert data["range"]["is_active"] is True
        assert data["range"]["is_terminal"] is False
        # The launched range is the one returned.
        assert data["range"]["request_id"] == _json(launch_resp)["range"]["request_id"]

    def test_does_not_return_another_users_range(self, authenticated_client, launch_range_via_api):
        owner_client, owner = authenticated_client(email="owner@example.com")
        launch_range_via_api(owner_client, owner)

        other_client, _other = authenticated_client(email="other@example.com")
        response = other_client.get(reverse("mission_control:get_range"))
        assert response.status_code == 200
        assert _json(response)["has_range"] is False


# ---------------------------------------------------------------------------
# launch_range
# ---------------------------------------------------------------------------


class TestLaunchRange:
    def _launch(self, client, body):
        return client.post(
            reverse("mission_control:launch_range"),
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_requires_login(self):
        response = Client().post(
            reverse("mission_control:launch_range"),
            data="{}",
            content_type="application/json",
        )
        assert response.status_code == 302

    def test_rejects_invalid_json(self, authenticated_client):
        client, _ = authenticated_client(email="badjson@example.com")
        response = client.post(
            reverse("mission_control:launch_range"),
            data="not json",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "Invalid JSON" in _json(response)["error"]

    def test_requires_agent(self, authenticated_client, hydratable_scenario):
        client, _ = authenticated_client(email="noagent@example.com")
        response = self._launch(client, {"scenario": hydratable_scenario.scenario_id})
        assert response.status_code == 400
        assert "agent" in _json(response)["error"].lower()

    def test_rejects_invalid_scenario(self, authenticated_client, make_agent):
        client, user = authenticated_client(email="badscenario@example.com")
        agent = make_agent(user)
        response = self._launch(client, {"agent_id": agent.id, "scenario": "does-not-exist"})
        assert response.status_code == 400
        assert "scenario" in _json(response)["error"].lower()

    def test_rejects_nonexistent_agent(self, authenticated_client, hydratable_scenario):
        client, _ = authenticated_client(email="ghostagent@example.com")
        response = self._launch(client, {"agent_id": 999999, "scenario": hydratable_scenario.scenario_id})
        assert response.status_code == 400

    def test_successful_launch_creates_range_and_audit(self, authenticated_client, make_agent, hydratable_scenario):
        client, user = authenticated_client(email="launch@example.com")
        agent = make_agent(user)

        assert Range.objects.count() == 0
        response = self._launch(client, {"agent_id": agent.id, "scenario": hydratable_scenario.scenario_id})

        assert response.status_code == 200
        data = _json(response)
        assert data["success"] is True
        assert data["range"]["scenario_id"] == hydratable_scenario.scenario_id
        assert data["range"]["status"] == "provisioning"
        # A real range row was persisted.
        assert Range.objects.count() == 1
        # The provision was audited.
        assert AuditLog.objects.filter(action=AuditLog.Action.PROVISION).exists()

    def test_rejects_second_concurrent_range(self, authenticated_client, make_agent, hydratable_scenario):
        client, user = authenticated_client(email="double@example.com")
        agent = make_agent(user)
        first = self._launch(client, {"agent_id": agent.id, "scenario": hydratable_scenario.scenario_id})
        assert first.status_code == 200

        second = self._launch(client, {"agent_id": agent.id, "scenario": hydratable_scenario.scenario_id})
        assert second.status_code == 400
        assert "active range" in _json(second)["error"].lower()
        # No second range row was created.
        assert Range.objects.count() == 1


# ---------------------------------------------------------------------------
# cancel_range / destroy_range
# ---------------------------------------------------------------------------


class TestCancelRange:
    def test_requires_login(self):
        response = Client().post(
            reverse("mission_control:cancel_range"),
            data="{}",
            content_type="application/json",
        )
        assert response.status_code == 302

    def test_requires_identifier(self, authenticated_client):
        client, _ = authenticated_client(email="cancelnoid@example.com")
        response = client.post(
            reverse("mission_control:cancel_range"),
            data="{}",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "request_id or range_id" in _json(response)["error"]

    def test_cancel_nonexistent_range(self, authenticated_client):
        client, _ = authenticated_client(email="cancelghost@example.com")
        response = client.post(
            reverse("mission_control:cancel_range"),
            data=json.dumps({"request_id": "00000000-0000-0000-0000-000000000000"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_successful_cancel_of_launched_range(self, authenticated_client, launch_range_via_api):
        client, user = authenticated_client(email="cancelok@example.com")
        launch_resp, _agent, _scenario = launch_range_via_api(client, user)
        request_id = _json(launch_resp)["range"]["request_id"]

        response = client.post(
            reverse("mission_control:cancel_range"),
            data=json.dumps({"request_id": request_id}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert _json(response)["success"] is True
        # The cancel was audited.
        assert AuditLog.objects.filter(action=AuditLog.Action.CANCEL).exists()


class TestDestroyRange:
    def test_requires_login(self):
        response = Client().post(
            reverse("mission_control:destroy_range"),
            data="{}",
            content_type="application/json",
        )
        assert response.status_code == 302

    def test_destroy_nonexistent_range(self, authenticated_client):
        client, _ = authenticated_client(email="destroyghost@example.com")
        response = client.post(
            reverse("mission_control:destroy_range"),
            data=json.dumps({"request_id": "00000000-0000-0000-0000-000000000000"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_successful_destroy_of_launched_range(self, authenticated_client, launch_range_via_api):
        client, user = authenticated_client(email="destroyok@example.com")
        launch_resp, _agent, _scenario = launch_range_via_api(client, user)
        request_id = _json(launch_resp)["range"]["request_id"]

        response = client.post(
            reverse("mission_control:destroy_range"),
            data=json.dumps({"request_id": request_id}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert _json(response)["success"] is True
        assert AuditLog.objects.filter(action=AuditLog.Action.DEPROVISION).exists()
