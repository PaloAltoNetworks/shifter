"""Behavior tests for the launch_range view.

Drives the real ``mission_control:launch_range`` endpoint → real
``cms_list_scenarios`` / ``cms_get_agent`` / ``cms_create_range`` against real
``Scenario`` / ``AgentConfig`` rows (a custom hydratable scenario + a real
Windows agent), instead of patching the cms service functions / ``render`` /
``logger``. Engine provisioning is a no-op (ECS unconfigured), so a launched
range stays ``provisioning`` and no cloud mock is needed.
"""

import json
import logging

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db

User = get_user_model()

SCENARIO_ID = "launch-behavior-test"
LAUNCH_URL = reverse("mission_control:launch_range")

# A scenario whose instances carry explicit os_types (kali attacker + windows
# victim with an XDR agent), so it hydrates cleanly with a single Windows agent.
HYDRATABLE_DEFINITION = {
    "instances": [
        {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
        {"name": "Target", "role": "victim", "os_type": "windows", "xdr_agent": True},
    ],
    "subnets": [{"name": "core", "instances": ["Attacker", "Target"]}],
    "ngfw": False,
}


def _json(response):
    return json.loads(response.content)


@pytest.fixture
def windows_os(db):
    from cms.models import OperatingSystem

    os_obj, _ = OperatingSystem.objects.get_or_create(
        slug="windows", defaults={"name": "Windows", "extensions": [".msi"]}
    )
    return os_obj


@pytest.fixture
def scenario(db):
    from cms.models import Scenario

    staff = User.objects.create_user(
        username="launch-author@example.com", email="launch-author@example.com", is_staff=True
    )
    return Scenario.objects.create(
        scenario_id=SCENARIO_ID,
        name="Launch Behavior",
        description="Hydratable scenario for launch_range behavior tests.",
        definition=HYDRATABLE_DEFINITION,
        created_by=staff,
        updated_by=staff,
    )


@pytest.fixture
def agent(db, windows_os, launch_client):
    from cms.models import AgentConfig

    _client, user = launch_client
    return AgentConfig.objects.create(
        name="Launch Agent",
        s3_key="agents/test/agent.msi",
        original_filename="agent.msi",
        file_size_bytes=5_000_000,
        sha256_hash="abc123",
        user=user,
        os=windows_os,
    )


@pytest.fixture
def launch_client(authenticated_client):
    return authenticated_client(email="launcher@example.com")


def _post(client, payload):
    return client.post(LAUNCH_URL, data=json.dumps(payload), content_type="application/json")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestLaunchRangeInputValidation:
    def test_returns_400_for_invalid_json(self, launch_client):
        client, _user = launch_client
        response = client.post(LAUNCH_URL, data="not valid json{", content_type="application/json")
        assert response.status_code == 400
        assert _json(response)["error"] == "Invalid JSON"

    def test_returns_400_for_empty_body(self, launch_client):
        client, _user = launch_client
        response = client.post(LAUNCH_URL, data="", content_type="application/json")
        assert response.status_code == 400
        assert _json(response)["error"] == "Invalid JSON"

    def test_returns_400_when_no_agent_provided(self, launch_client, scenario):
        client, _user = launch_client
        response = _post(client, {"scenario": SCENARIO_ID})
        assert response.status_code == 400
        assert "agent_id" in _json(response)["error"]

    @pytest.mark.parametrize("bad_agent_id", [None, 0])
    def test_returns_400_for_falsy_agent_id(self, launch_client, scenario, bad_agent_id):
        client, _user = launch_client
        response = _post(client, {"agent_id": bad_agent_id, "scenario": SCENARIO_ID})
        assert response.status_code == 400
        assert "agent_id" in _json(response)["error"]


# ---------------------------------------------------------------------------
# Scenario validation
# ---------------------------------------------------------------------------


class TestLaunchRangeScenarioValidation:
    def test_accepts_a_valid_scenario(self, launch_client, agent, scenario):
        client, _user = launch_client
        response = _post(client, {"agent_id": agent.id, "scenario": SCENARIO_ID})
        assert response.status_code == 200

    def test_rejects_unknown_scenario(self, launch_client, agent, scenario):
        client, _user = launch_client
        response = _post(client, {"agent_id": agent.id, "scenario": "no-such-scenario"})
        assert response.status_code == 400
        assert "Invalid" in _json(response)["error"]

    def test_omitting_scenario_defaults_to_basic(self, launch_client, agent, scenario):
        """When no scenario is given the view defaults to 'basic' (a real builtin).

        'basic' is a valid scenario whose victim is `os_type: from_agent`, so it
        hydrates against this Windows agent (the victim resolves to Windows) and
        launches — proving the default was accepted, not rejected as 'Invalid
        scenario'. (Regression: 'basic' previously 400'd in hydration even with
        an agent because `from_agent` resolution was gated on `xdr_agent`.)
        """
        client, _user = launch_client
        response = _post(client, {"agent_id": agent.id})
        assert response.status_code == 200
        assert _json(response)["range"]["scenario_id"] == "basic"


# ---------------------------------------------------------------------------
# Success behavior
# ---------------------------------------------------------------------------


class TestLaunchRangeSuccess:
    def test_returns_success_with_range_dict(self, launch_client, agent, scenario):
        client, user = launch_client
        response = _post(client, {"agent_id": agent.id, "scenario": SCENARIO_ID})

        assert response.status_code == 200
        data = _json(response)
        assert data["success"] is True
        range_data = data["range"]
        assert isinstance(range_data, dict)
        assert range_data["scenario_id"] == SCENARIO_ID
        assert range_data["user_id"] == user.id
        assert range_data["status"] == "provisioning"
        assert isinstance(range_data["instances"], list)
        # Computed RangeContext fields (provisioning, not yet ready/terminal).
        assert range_data["is_ready"] is False
        assert range_data["is_terminal"] is False
        assert range_data["is_active"] is True


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestLaunchRangeErrorHandling:
    def test_active_range_conflict_maps_to_authored_literal(self, launch_client, agent, scenario):
        """A second launch while a range is active is rejected with the authored
        'already have an active range' guidance (never echoing str(e))."""
        client, _user = launch_client
        first = _post(client, {"agent_id": agent.id, "scenario": SCENARIO_ID})
        assert first.status_code == 200

        second = _post(client, {"agent_id": agent.id, "scenario": SCENARIO_ID})
        assert second.status_code == 400
        assert _json(second)["error"] == "You already have an active range"

    def test_unknown_agent_maps_to_safe_message(self, launch_client, scenario):
        """A non-existent agent id surfaces a classified, non-leaking message."""
        client, _user = launch_client
        response = _post(client, {"agent_id": 999999, "scenario": SCENARIO_ID})
        assert response.status_code == 400
        # Classified literal, not the raw exception text.
        assert _json(response)["error"] in {"Resource not found", "Agent not available"}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestLaunchRangeLogging:
    def test_logs_info_on_successful_launch(self, launch_client, agent, scenario, caplog):
        client, _user = launch_client
        with caplog.at_level(logging.INFO, logger="mission_control.views"):
            response = _post(client, {"agent_id": agent.id, "scenario": SCENARIO_ID})
        assert response.status_code == 200
        assert "Range launched" in caplog.text

    def test_no_info_log_on_validation_failure(self, launch_client, scenario, caplog):
        client, _user = launch_client
        with caplog.at_level(logging.INFO, logger="mission_control.views"):
            response = _post(client, {"scenario": SCENARIO_ID})  # no agent
        assert response.status_code == 400
        assert "Range launched" not in caplog.text
