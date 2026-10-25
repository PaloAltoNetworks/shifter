"""Prepared lease administration accepts independent policy service principals."""

import pytest
from django.contrib.auth.models import Group

from cms import services
from shared.mission_control_lease import MissionControlLeasePolicy
from tests.workspaces.test_account_policy_admin import Provider, _actor

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("kind", ["human", "service"])
def test_policy_administrator_reads_replaces_and_resets_lease_policy(monkeypatch, kind):
    actor = _actor(kind, actions=frozenset({"installation.manage_lease_policy"}))
    monkeypatch.setattr("cms.services._range_lease_policy_support.configured_authorization_provider", Provider)
    policy = MissionControlLeasePolicy(initial_days=1, extension_days=1, maximum_days=3, extensions_enabled=True)
    audit = services.LeasePolicyAuditContext(
        actor_type="principal", actor_id=None, actor_principal_uuid=actor.principal.uuid
    )
    before = services.get_mission_control_lease_settings(actor)
    services.replace_tenant_lease_policy(actor, policy, expected_revision=before.tenant_revision, audit=audit)
    current = services.get_mission_control_lease_settings(actor)
    assert current.tenant_override.policy == policy
    group = Group.objects.create(name="Lease group")
    services.replace_group_lease_policy(actor, group.pk, policy, expected_revision=0, audit=audit)
    current = services.get_mission_control_lease_settings(actor)
    group_state = next(item for item in current.groups if item.group_id == group.pk)
    services.reset_group_lease_policy(actor, group.pk, expected_revision=group_state.revision, audit=audit)
    services.reset_tenant_lease_policy(actor, expected_revision=current.tenant_revision, audit=audit)
    assert services.get_mission_control_lease_settings(actor).tenant_override is None


def test_policy_lease_denial_and_ceiling_preserve_settings(monkeypatch):
    actor = _actor("service", actions=frozenset({"installation.manage_lease_policy"}))
    monkeypatch.setattr(
        "cms.services._range_lease_policy_support.configured_authorization_provider", lambda: Provider(allowed=False)
    )
    with pytest.raises(services.MissionControlLeasePolicyAdminError):
        services.get_mission_control_lease_settings(actor)
    monkeypatch.setattr("cms.services._range_lease_policy_support.configured_authorization_provider", Provider)
    with pytest.raises(services.MissionControlLeasePolicyAdminError):
        services.get_mission_control_lease_settings(
            _actor("service", actions=frozenset({"installation.manage_principals"}))
        )
