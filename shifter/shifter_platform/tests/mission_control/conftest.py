"""Shared fixtures for mission_control behavior tests.

These tests drive the real Django views/URLs with a real database and assert
observable behavior (HTTP responses + persisted ORM state) instead of patching
first-party service/view internals. The only boundaries that would need mocking
are process/network/cloud SDKs; in the test settings ECS/local-provisioner are
unconfigured, so range provisioning is a no-op and no cloud mock is required.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

import cms.scenarios.hydrator as _hydrator
from cms.models import AgentConfig, OperatingSystem, Scenario
from cms.scenarios.registry import load_scenario_template as _GENUINE_LOAD_SCENARIO

User = get_user_model()


@pytest.fixture(autouse=True)
def _restore_real_scenario_loader():
    """Guard the scenario loader binding against cross-suite mock leakage.

    Legacy mock-coupled cms suites (``test_scenario_hydrator``,
    ``test_services_range*``) patch ``cms.scenarios.hydrator.load_scenario``.
    Under pytest-xdist that patched binding can leak into a worker that later
    runs these behavior tests, which drive real scenario hydration, leaving
    ``load_scenario`` a ``Mock``. Rebind it to the genuine loader (captured at
    import, before any patch is active) so each test starts from real state.
    Remove once those cms suites are rewritten to behavior tests (#957).
    """
    _hydrator.load_scenario = _GENUINE_LOAD_SCENARIO
    yield


# A scenario definition whose victim resolves to a Windows agent
# (xdr_agent=True), so create_range hydrates cleanly with a single
# Windows AgentConfig and no cloud configured.
HYDRATABLE_DEFINITION: dict[str, Any] = {
    "instances": [
        {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
        {"name": "Target", "role": "victim", "os_type": "windows", "xdr_agent": True},
    ],
    "subnets": [{"name": "core", "instances": ["Attacker", "Target"]}],
    "ngfw": False,
}


@pytest.fixture
def windows_os(db) -> OperatingSystem:
    """The seeded (or created) Windows operating system row."""
    os_obj, _ = OperatingSystem.objects.get_or_create(
        slug="windows", defaults={"name": "Windows", "extensions": [".msi"]}
    )
    return os_obj


@pytest.fixture
def linux_os(db) -> OperatingSystem:
    """A Linux operating system row for agent-OS variations."""
    os_obj, _ = OperatingSystem.objects.get_or_create(
        slug="linux-debian", defaults={"name": "Linux (Debian/Ubuntu)", "extensions": [".deb"]}
    )
    return os_obj


@pytest.fixture
def make_agent(db, windows_os) -> Callable[..., AgentConfig]:
    """Factory creating a real AgentConfig owned by ``user``."""

    def _make(user, *, os=None, name="Test XDR Agent", **overrides) -> AgentConfig:
        fields: dict[str, Any] = {
            "name": name,
            "s3_key": "agents/test/agent.msi",
            "original_filename": "agent.msi",
            "file_size_bytes": 50_000_000,
            "sha256_hash": "abc123",
            "user": user,
            "os": os or windows_os,
        }
        fields.update(overrides)
        return AgentConfig.objects.create(**fields)

    return _make


@pytest.fixture
def hydratable_scenario(db) -> Scenario:
    """A DB custom scenario that hydrates with a single Windows agent."""
    staff = User.objects.create_user(
        username="scenario-author@example.com",
        email="scenario-author@example.com",
        is_staff=True,
    )
    return Scenario.objects.create(
        scenario_id="behavior-test",
        name="Behavior Test Range",
        description="Hydratable scenario for behavior tests.",
        definition=HYDRATABLE_DEFINITION,
        created_by=staff,
        updated_by=staff,
    )


@pytest.fixture
def launch_range_via_api(make_agent, hydratable_scenario) -> Callable[..., tuple[Any, AgentConfig, str]]:
    """Launch a real range for ``(client, user)`` and return (response, agent, scenario_id).

    Drives the real launch endpoint so downstream get/cancel/destroy tests
    operate on genuinely-persisted range state.
    """

    def _launch(client, user, *, scenario_id: str | None = None) -> tuple[Any, AgentConfig, str]:
        agent = make_agent(user)
        scenario = scenario_id or hydratable_scenario.scenario_id
        response = client.post(
            reverse("mission_control:launch_range"),
            data=json.dumps({"agent_id": agent.id, "scenario": scenario}),
            content_type="application/json",
        )
        return response, agent, scenario

    return _launch
