"""Runtime Mission Control lease-policy hierarchy tests (#2169)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import override_settings

from shared.audit import AuditAction, AuditEntityType
from shared.mission_control_lease import MissionControlLeasePolicy
from shared.models import AuditLog

pytestmark = pytest.mark.django_db

User = get_user_model()


def _policy(initial: int, extension: int, maximum: int, *, enabled: bool = True) -> MissionControlLeasePolicy:
    return MissionControlLeasePolicy(
        initial_days=initial,
        extension_days=extension,
        maximum_days=maximum,
        extensions_enabled=enabled,
    )


@pytest.fixture
def admin():
    return User.objects.create_superuser(username="lease-admin", email="lease-admin@example.com", password="pw")


@pytest.fixture
def owner():
    return User.objects.create_user(username="lease-owner", email="lease-owner@example.com")


def _audit(actor_id: int):
    from cms.services import LeasePolicyAuditContext

    return LeasePolicyAuditContext(
        actor_type="user",
        actor_id=actor_id,
        request_id="req-2169",
        source_ip="192.0.2.10",
        user_agent="pytest",
    )


def test_absent_runtime_rows_use_the_deployment_fallback_and_default_projection(admin, owner):
    from cms.services import get_mission_control_lease_settings, resolve_mission_control_lease_policy

    baseline = _policy(30, 30, 365)
    with override_settings(MISSION_CONTROL_LEASE_POLICY=baseline):
        resolved = resolve_mission_control_lease_policy(owner)
        settings = get_mission_control_lease_settings(admin)

    assert resolved.policy == baseline
    assert resolved.source == "deployment"
    assert resolved.tenant_revision == 0
    assert resolved.group_revisions == ()
    assert settings.baseline == baseline
    assert settings.tenant_override is None
    assert settings.effective_tenant == baseline
    assert settings.effective_source == "deployment"


def test_tenant_and_multiple_group_policies_resolve_restrictively_and_audit(admin, owner):
    from cms.services import (
        replace_group_lease_policy,
        replace_tenant_lease_policy,
        resolve_mission_control_lease_policy,
    )

    red = Group.objects.create(name="Red Team")
    blue = Group.objects.create(name="Blue Team")
    owner.groups.add(red, blue)
    tenant = replace_tenant_lease_policy(admin, _policy(20, 12, 180), expected_revision=0, audit=_audit(admin.pk))
    red_result = replace_group_lease_policy(
        admin,
        red.pk,
        _policy(14, 9, 120),
        expected_revision=0,
        audit=_audit(admin.pk),
    )
    blue_result = replace_group_lease_policy(
        admin,
        blue.pk,
        _policy(7, 4, 90, enabled=False),
        expected_revision=0,
        audit=_audit(admin.pk),
    )

    resolved = resolve_mission_control_lease_policy(owner)

    assert tenant.revision == red_result.revision == blue_result.revision == 1
    assert resolved.policy == _policy(7, 4, 90, enabled=False)
    assert resolved.source == "group"
    assert resolved.tenant_revision == 1
    assert [(item.group_id, item.revision) for item in resolved.group_revisions] == [
        (red.pk, 1),
        (blue.pk, 1),
    ]
    assert (
        AuditLog.objects.filter(
            entity_type=AuditEntityType.CONFIG,
            action=AuditAction.UPDATE,
            actor_id=admin.pk,
        ).count()
        == 3
    )


def test_group_policy_never_grants_or_follows_provider_claims(admin, owner):
    from cms.services import replace_group_lease_policy, resolve_mission_control_lease_policy

    group = Group.objects.create(name="Provider String Only")
    replace_group_lease_policy(admin, group.pk, _policy(5, 5, 30), expected_revision=0, audit=_audit(admin.pk))
    # The provider-copied profile string is not committed Django group membership.
    owner.profile.cognito_groups = [group.name]
    owner.profile.save(update_fields=["cognito_groups"])

    resolved = resolve_mission_control_lease_policy(owner)

    assert resolved.source == "deployment"
    assert resolved.policy == MissionControlLeasePolicy()


def test_self_service_participant_group_is_ineligible(admin):
    from cms.services import MissionControlLeasePolicyAdminError, replace_group_lease_policy

    participant, _created = Group.objects.get_or_create(name="CTF Participant")

    with pytest.raises(MissionControlLeasePolicyAdminError) as caught:
        replace_group_lease_policy(
            admin,
            participant.pk,
            _policy(5, 5, 30),
            expected_revision=0,
            audit=_audit(admin.pk),
        )

    assert caught.value.kind.value == "group_ineligible"


def test_parent_change_that_invalidates_a_child_is_rejected_without_mutation(admin):
    from cms.models import MissionControlTenantLeasePolicy
    from cms.services import (
        MissionControlLeasePolicyAdminError,
        replace_group_lease_policy,
        replace_tenant_lease_policy,
    )

    group = Group.objects.create(name="Bounded Group")
    tenant = replace_tenant_lease_policy(admin, _policy(30, 30, 365), expected_revision=0, audit=_audit(admin.pk))
    replace_group_lease_policy(admin, group.pk, _policy(20, 20, 180), expected_revision=0, audit=_audit(admin.pk))

    with pytest.raises(MissionControlLeasePolicyAdminError) as caught:
        replace_tenant_lease_policy(
            admin,
            _policy(10, 10, 90),
            expected_revision=tenant.revision,
            audit=_audit(admin.pk),
        )

    assert caught.value.kind.value == "child_policy_conflict"
    assert MissionControlTenantLeasePolicy.objects.get().maximum_days == 365


def test_group_policy_cannot_exceed_the_effective_tenant_maximum(admin):
    from cms.models import MissionControlGroupLeasePolicy, MissionControlGroupLeasePolicyRevision
    from cms.services import (
        MissionControlLeasePolicyAdminError,
        replace_group_lease_policy,
        replace_tenant_lease_policy,
    )

    group = Group.objects.create(name="Tenant bounded group")
    replace_tenant_lease_policy(admin, _policy(30, 30, 90), expected_revision=0, audit=_audit(admin.pk))

    with pytest.raises(MissionControlLeasePolicyAdminError) as caught:
        replace_group_lease_policy(
            admin,
            group.pk,
            _policy(30, 30, 120),
            expected_revision=0,
            audit=_audit(admin.pk),
        )

    assert caught.value.kind.value == "invalid_policy"
    assert not MissionControlGroupLeasePolicy.objects.filter(group=group).exists()
    assert not MissionControlGroupLeasePolicyRevision.objects.filter(group=group).exists()


@pytest.mark.parametrize("operation", ["replace", "reset"])
def test_group_policy_commands_reject_a_missing_group(admin, operation):
    from cms.services import (
        MissionControlLeasePolicyAdminError,
        replace_group_lease_policy,
        reset_group_lease_policy,
    )

    missing_group_id = 999_999
    with pytest.raises(MissionControlLeasePolicyAdminError) as caught:
        if operation == "replace":
            replace_group_lease_policy(
                admin,
                missing_group_id,
                _policy(30, 30, 90),
                expected_revision=0,
                audit=_audit(admin.pk),
            )
        else:
            reset_group_lease_policy(
                admin,
                missing_group_id,
                expected_revision=0,
                audit=_audit(admin.pk),
            )

    assert caught.value.kind.value == "group_not_found"


def test_stale_revision_and_non_superuser_are_rejected(admin, owner):
    from cms.services import MissionControlLeasePolicyAdminError, replace_tenant_lease_policy

    current = replace_tenant_lease_policy(admin, _policy(20, 10, 180), expected_revision=0, audit=_audit(admin.pk))

    with pytest.raises(MissionControlLeasePolicyAdminError) as stale:
        replace_tenant_lease_policy(
            admin,
            _policy(21, 10, 180),
            expected_revision=current.revision - 1,
            audit=_audit(admin.pk),
        )
    with pytest.raises(MissionControlLeasePolicyAdminError) as forbidden:
        replace_tenant_lease_policy(owner, _policy(20, 10, 180), expected_revision=1, audit=_audit(owner.pk))

    assert stale.value.kind.value == "revision_conflict"
    assert forbidden.value.kind.value == "forbidden"


def test_tenant_revision_is_not_reused_across_reset_and_recreation(admin):
    from cms.services import (
        MissionControlLeasePolicyAdminError,
        get_mission_control_lease_settings,
        replace_tenant_lease_policy,
        reset_tenant_lease_policy,
    )

    first = replace_tenant_lease_policy(admin, _policy(20, 10, 180), expected_revision=0, audit=_audit(admin.pk))
    reset_tenant_lease_policy(admin, expected_revision=first.revision, audit=_audit(admin.pk))
    fallback = get_mission_control_lease_settings(admin)
    second = replace_tenant_lease_policy(
        admin,
        _policy(14, 7, 90),
        expected_revision=fallback.tenant_revision,
        audit=_audit(admin.pk),
    )

    assert fallback.tenant_override is None
    assert fallback.tenant_revision == 2
    assert second.revision == 3
    with pytest.raises(MissionControlLeasePolicyAdminError) as stale_replace:
        replace_tenant_lease_policy(
            admin,
            _policy(7, 7, 30),
            expected_revision=first.revision,
            audit=_audit(admin.pk),
        )
    with pytest.raises(MissionControlLeasePolicyAdminError) as stale_reset:
        reset_tenant_lease_policy(admin, expected_revision=first.revision, audit=_audit(admin.pk))

    assert stale_replace.value.kind.value == "revision_conflict"
    assert stale_reset.value.kind.value == "revision_conflict"


def test_group_revision_is_not_reused_across_reset_and_recreation(admin):
    from cms.services import (
        MissionControlLeasePolicyAdminError,
        get_mission_control_lease_settings,
        replace_group_lease_policy,
        reset_group_lease_policy,
    )

    group = Group.objects.create(name="Revision fenced group")
    first = replace_group_lease_policy(
        admin,
        group.pk,
        _policy(20, 10, 180),
        expected_revision=0,
        audit=_audit(admin.pk),
    )
    reset_group_lease_policy(admin, group.pk, expected_revision=first.revision, audit=_audit(admin.pk))
    inherited = next(item for item in get_mission_control_lease_settings(admin).groups if item.group_id == group.pk)
    second = replace_group_lease_policy(
        admin,
        group.pk,
        _policy(14, 7, 90),
        expected_revision=inherited.revision,
        audit=_audit(admin.pk),
    )

    assert inherited.override is None
    assert inherited.revision == 2
    assert second.revision == 3
    with pytest.raises(MissionControlLeasePolicyAdminError) as stale_replace:
        replace_group_lease_policy(
            admin,
            group.pk,
            _policy(7, 7, 30),
            expected_revision=first.revision,
            audit=_audit(admin.pk),
        )
    with pytest.raises(MissionControlLeasePolicyAdminError) as stale_reset:
        reset_group_lease_policy(
            admin,
            group.pk,
            expected_revision=first.revision,
            audit=_audit(admin.pk),
        )

    assert stale_replace.value.kind.value == "revision_conflict"
    assert stale_reset.value.kind.value == "revision_conflict"


def test_reset_restores_current_deployment_fallback_and_checks_children(admin):
    from cms.services import (
        MissionControlLeasePolicyAdminError,
        replace_group_lease_policy,
        replace_tenant_lease_policy,
        reset_group_lease_policy,
        reset_tenant_lease_policy,
        resolve_mission_control_lease_policy,
    )

    group = Group.objects.create(name="Runtime Group")
    owner = User.objects.create_user(username="reset-owner")
    owner.groups.add(group)
    tenant = replace_tenant_lease_policy(admin, _policy(10, 5, 90), expected_revision=0, audit=_audit(admin.pk))
    child = replace_group_lease_policy(admin, group.pk, _policy(7, 3, 60), expected_revision=0, audit=_audit(admin.pk))

    with override_settings(MISSION_CONTROL_LEASE_POLICY=_policy(5, 5, 30)):
        with pytest.raises(MissionControlLeasePolicyAdminError) as caught:
            reset_tenant_lease_policy(admin, expected_revision=tenant.revision, audit=_audit(admin.pk))
        assert caught.value.kind.value == "child_policy_conflict"
        reset_group_lease_policy(admin, group.pk, expected_revision=child.revision, audit=_audit(admin.pk))
        reset_tenant_lease_policy(admin, expected_revision=tenant.revision, audit=_audit(admin.pk))
        resolved = resolve_mission_control_lease_policy(owner)

    assert resolved.source == "deployment"
    assert resolved.policy == _policy(5, 5, 30)


def test_strict_audit_failure_rolls_back_policy_write(admin, monkeypatch):
    from cms.models import MissionControlTenantLeasePolicy
    from cms.services import replace_tenant_lease_policy

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("cms.services._range_lease_policy_support.audit_log", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        replace_tenant_lease_policy(admin, _policy(20, 10, 180), expected_revision=0, audit=_audit(admin.pk))

    assert not MissionControlTenantLeasePolicy.objects.exists()


def test_inactive_superuser_is_not_authorized(admin):
    from cms.services import MissionControlLeasePolicyAdminError, get_mission_control_lease_settings

    admin.is_active = False
    admin.save(update_fields=["is_active"])
    with pytest.raises(MissionControlLeasePolicyAdminError) as caught:
        get_mission_control_lease_settings(admin)
    assert caught.value.kind.value == "forbidden"


def test_database_constraints_reject_invalid_singleton_revision_and_group_policy():
    from cms.models import MissionControlGroupLeasePolicy, MissionControlTenantLeasePolicy

    with pytest.raises(IntegrityError), transaction.atomic():
        MissionControlTenantLeasePolicy.objects.create(
            id=2,
            initial_days=30,
            extension_days=30,
            maximum_days=365,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        MissionControlTenantLeasePolicy.objects.create(
            initial_days=30,
            extension_days=30,
            maximum_days=365,
            revision=0,
        )

    group = Group.objects.create(name="Invalid policy row")
    with pytest.raises(IntegrityError), transaction.atomic():
        MissionControlGroupLeasePolicy.objects.create(
            group=group,
            initial_days=91,
            extension_days=30,
            maximum_days=90,
        )
