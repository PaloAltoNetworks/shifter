"""Pytest fixtures and helpers for CMS tests.

Provides shared model builders and fixtures used across CMS test modules.
"""

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db.models.base import ModelState
from django.utils import timezone

import cms.scenarios.hydrator as _hydrator
from cms.models import AgentConfig, Credential, CredentialType, OperatingSystem, Scenario
from cms.scenarios.registry import load_scenario_template as _GENUINE_LOAD_SCENARIO

User = get_user_model()


# -----------------------------------------------------------------------------
# Behavior-test fixtures: real scenario hydration against the test DB
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_real_scenario_loader():
    """Guard the scenario loader binding against cross-suite mock leakage.

    Legacy mock-coupled cms suites patch ``cms.scenarios.hydrator.load_scenario``.
    Under pytest-xdist that patched binding can leak into a worker that later
    runs the behavior tests, which drive real scenario hydration. Rebind it to
    the genuine loader (captured at import, before any patch is active) so each
    test starts from real state.
    """
    _hydrator.load_scenario = _GENUINE_LOAD_SCENARIO
    yield


# A scenario whose victim resolves to a Windows agent (xdr_agent=True), so
# create_range hydrates cleanly with a single Windows AgentConfig and no cloud.
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
    os_obj, _ = OperatingSystem.objects.get_or_create(
        slug="windows", defaults={"name": "Windows", "extensions": [".msi"]}
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
        username="cms-scenario-author@example.com",
        email="cms-scenario-author@example.com",
        is_staff=True,
    )
    return Scenario.objects.create(
        scenario_id="cms-behavior-test",
        name="CMS Behavior Test Range",
        description="Hydratable scenario for cms behavior tests.",
        definition=HYDRATABLE_DEFINITION,
        created_by=staff,
        updated_by=staff,
    )


@pytest.fixture
def provision_range(make_agent, hydratable_scenario) -> Callable[..., Any]:
    """Factory: create a real range for ``user`` (full hydrate->engine->persist
    stack), assign it a ``range_id``, and return the cms RangeInstance.

    The matching engine ``Range``/``Request`` rows are created too, so range
    lifecycle services (destroy/cancel/pause/resume) operate on genuine state.
    """
    from cms import services
    from cms.models import RangeInstance

    def _make(user, *, range_id=42, engine_status=None):
        services.create_range(user, hydratable_scenario.scenario_id, {"windows": make_agent(user).id})
        ri = RangeInstance.objects.get(user_id=user.id)
        ri.range_id = range_id
        ri.save(update_fields=["range_id"])
        if engine_status is not None:
            from engine.models import Range as EngineRange

            EngineRange.objects.filter(user=user).update(status=engine_status)
        return ri

    return _make


# -----------------------------------------------------------------------------
# In-memory model builders (no DB required)
# -----------------------------------------------------------------------------


@pytest.fixture
def credential_type_obj():
    """Create a CredentialType instance in memory (no DB)."""
    ct = CredentialType(
        name="Deployment Profile",
        slug="deployment_profile",
        spec_slug="credential.deployment_profile",
    )
    ct.pk = 1
    ct.id = 1
    return ct


@pytest.fixture
def scm_credential_type_obj():
    """Create an SCM CredentialType instance in memory (no DB)."""
    ct = CredentialType(
        name="SCM Credential",
        slug="scm",
        spec_slug="credential.scm",
    )
    ct.pk = 2
    ct.id = 2
    return ct


def make_credential(credential_type_obj, pk=1, **overrides):
    """Build a Credential instance in memory using _id fields to bypass FK checks.

    Uses __new__ + manual __dict__ population to avoid Django's FK descriptor
    type-checking (which rejects MagicMock users). The _state object is
    initialized manually to keep FK cache access working.
    """
    cred = Credential.__new__(Credential)
    cred._state = ModelState()
    # Set fields directly to avoid FK descriptor type checks
    cred.__dict__["name"] = overrides.get("name", "My Credential")
    cred.__dict__["user_id"] = overrides.get("user_id", 1)
    cred.__dict__["credential_type_id"] = credential_type_obj.pk
    cred.__dict__["data"] = overrides.get("data", {"authcode": "D1234567"})
    cred.__dict__["deleted_at"] = overrides.get("deleted_at")
    cred.__dict__["expires_at"] = overrides.get("expires_at")
    cred.__dict__["created_at"] = overrides.get("created_at", timezone.now())
    # Cache the FK object so descriptor access works without DB
    cred._state.fields_cache["credential_type"] = credential_type_obj
    cred.pk = pk
    cred.id = pk
    return cred
