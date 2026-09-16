"""Runtime Mission Control lease-policy resolution and administration (#2169)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.models import Group
from django.db import connection, transaction

from cms.models import (
    MissionControlGroupLeasePolicy,
    MissionControlGroupLeasePolicyRevision,
    MissionControlTenantLeasePolicy,
)
from shared.mission_control_lease import MissionControlLeasePolicy

from ._range_lease_policy_support import (
    _INELIGIBLE_GROUP_NAMES,
    LeasePolicyAuditContext,
    LeasePolicyGroupRevision,
    LeasePolicyGroupSettings,
    LeasePolicyOverride,
    MissionControlLeasePolicyAdminError,
    MissionControlLeasePolicySettings,
    ResolvedMissionControlLeasePolicy,
    _advance_revision,
    _assert_active_superuser,
    _canonical_policy,
    _current_revision,
    _deployment_policy,
    _effective_tenant,
    _eligible_group_for_update,
    _error,
    _expected_revision,
    _group_revision_row,
    _lock_policy_namespace,
    _matching_group_rows,
    _override_from_row,
    _policy_from_row,
    _policy_state,
    _tenant_revision_row,
    _tenant_row,
    _validate_children,
    _write_audit,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def resolve_mission_control_lease_policy(
    user: User,
    *,
    for_update: bool = False,
) -> ResolvedMissionControlLeasePolicy:
    """Resolve fallback -> tenant -> restrictive group policy for an authenticated owner."""
    if for_update:
        if not connection.in_atomic_block:
            raise RuntimeError("Locked lease-policy resolution requires an active transaction")
        _lock_policy_namespace()
    tenant, tenant_revision, tenant_source = _effective_tenant(for_update=for_update)
    rows = _matching_group_rows(user, for_update=for_update)
    if not rows:
        return ResolvedMissionControlLeasePolicy(tenant, tenant_source, tenant_revision, ())

    group_policies = [_policy_from_row(row) for row in rows]
    maximum_days = min(tenant.maximum_days, *(policy.maximum_days for policy in group_policies))
    initial_days = min(maximum_days, *(policy.initial_days for policy in group_policies))
    effective = _canonical_policy(
        {
            "initial_days": initial_days,
            "extension_days": min(policy.extension_days for policy in group_policies),
            "maximum_days": maximum_days,
            "extensions_enabled": tenant.extensions_enabled
            and all(policy.extensions_enabled for policy in group_policies),
        }
    )
    revisions = tuple(LeasePolicyGroupRevision(row.group_id, row.revision) for row in rows)
    return ResolvedMissionControlLeasePolicy(effective, "group", tenant_revision, revisions)


def get_mission_control_lease_settings(actor: User) -> MissionControlLeasePolicySettings:
    """Return the bounded settings projection for an active platform superuser."""
    _assert_active_superuser(actor)
    baseline = _deployment_policy()
    tenant_row = _tenant_row(for_update=False)
    tenant_revision_row = _tenant_revision_row(for_update=False)
    tenant_revision = _current_revision(tenant_revision_row, tenant_row)
    tenant_override = _override_from_row(tenant_row) if tenant_row is not None else None
    effective_tenant = tenant_override.policy if tenant_override else baseline
    policy_by_group = {
        row.group_id: row
        for row in MissionControlGroupLeasePolicy.objects.select_related("group").exclude(
            group__name__in=_INELIGIBLE_GROUP_NAMES
        )
    }
    revision_by_group = {
        row.group_id: row.revision
        for row in MissionControlGroupLeasePolicyRevision.objects.exclude(group__name__in=_INELIGIBLE_GROUP_NAMES)
    }
    groups = tuple(
        LeasePolicyGroupSettings(
            group_id=group.pk,
            group_name=group.name,
            revision=revision_by_group.get(
                group.pk,
                policy_by_group[group.pk].revision if group.pk in policy_by_group else 0,
            ),
            override=_override_from_row(policy_by_group[group.pk]) if group.pk in policy_by_group else None,
        )
        for group in Group.objects.exclude(name__in=_INELIGIBLE_GROUP_NAMES).order_by("name", "pk")
    )
    return MissionControlLeasePolicySettings(
        baseline=baseline,
        tenant_revision=tenant_revision,
        tenant_override=tenant_override,
        effective_tenant=effective_tenant,
        effective_source="runtime" if tenant_override else "deployment",
        groups=groups,
    )


def replace_tenant_lease_policy(
    actor: User,
    policy: MissionControlLeasePolicy,
    *,
    expected_revision: int,
    audit: LeasePolicyAuditContext,
) -> LeasePolicyOverride:
    """Create or replace the complete tenant override under revision CAS."""
    _assert_active_superuser(actor)
    canonical = _canonical_policy(policy)
    expected = _expected_revision(expected_revision)
    with transaction.atomic():
        _lock_policy_namespace()
        revision_row = _tenant_revision_row(for_update=True)
        row = _tenant_row(for_update=True)
        actual = _current_revision(revision_row, row)
        if expected != actual:
            raise _error(
                MissionControlLeasePolicyAdminError.Kind.REVISION_CONFLICT,
                "Mission Control lease policy changed; refresh and try again",
            )
        children = list(MissionControlGroupLeasePolicy.objects.select_for_update().order_by("group_id"))
        _validate_children(canonical.maximum_days, children)
        if row is not None and _policy_from_row(row) == canonical:
            return _override_from_row(row)
        previous = _policy_state(_policy_from_row(row), row.revision, scope="tenant") if row else None
        next_revision = _advance_revision(revision_row, actual=actual)
        if row is None:
            row = MissionControlTenantLeasePolicy.objects.create(
                **canonical.model_dump(),
                revision=next_revision,
            )
        else:
            for field, value in canonical.model_dump().items():
                setattr(row, field, value)
            row.revision = next_revision
            row.save(
                update_fields=[
                    "initial_days",
                    "extension_days",
                    "maximum_days",
                    "extensions_enabled",
                    "revision",
                    "updated_at",
                ]
            )
        _write_audit(
            entity_id=row.pk,
            context="mission_control_tenant_lease_policy",
            audit=audit,
            previous=previous,
            current=_policy_state(canonical, row.revision, scope="tenant"),
        )
        return _override_from_row(row)


def reset_tenant_lease_policy(
    actor: User,
    *,
    expected_revision: int,
    audit: LeasePolicyAuditContext,
) -> None:
    """Remove the tenant override after validating children against the live fallback."""
    _assert_active_superuser(actor)
    expected = _expected_revision(expected_revision)
    with transaction.atomic():
        _lock_policy_namespace()
        revision_row = _tenant_revision_row(for_update=True)
        row = _tenant_row(for_update=True)
        actual = _current_revision(revision_row, row)
        if expected != actual:
            raise _error(
                MissionControlLeasePolicyAdminError.Kind.REVISION_CONFLICT,
                "Mission Control lease policy changed; refresh and try again",
            )
        if row is None:
            return
        children = list(MissionControlGroupLeasePolicy.objects.select_for_update().order_by("group_id"))
        baseline = _deployment_policy()
        _validate_children(baseline.maximum_days, children)
        previous = _policy_state(_policy_from_row(row), row.revision, scope="tenant")
        next_revision = _advance_revision(revision_row, actual=actual)
        _write_audit(
            entity_id=row.pk,
            context="mission_control_tenant_lease_policy_reset",
            audit=audit,
            previous=previous,
            current={"scope": "tenant", "source": "deployment", "revision": next_revision},
        )
        row.delete()


def replace_group_lease_policy(
    actor: User,
    group_id: int,
    policy: MissionControlLeasePolicy,
    *,
    expected_revision: int,
    audit: LeasePolicyAuditContext,
) -> LeasePolicyOverride:
    """Create or replace one complete eligible-group policy under revision CAS."""
    _assert_active_superuser(actor)
    canonical = _canonical_policy(policy)
    expected = _expected_revision(expected_revision)
    with transaction.atomic():
        _lock_policy_namespace()
        tenant, _tenant_revision, _source = _effective_tenant(for_update=True)
        group = _eligible_group_for_update(group_id)
        if canonical.initial_days > tenant.maximum_days or canonical.maximum_days > tenant.maximum_days:
            raise _error(
                MissionControlLeasePolicyAdminError.Kind.INVALID_POLICY,
                "Group lease policy exceeds the effective tenant maximum",
            )
        revision_row = _group_revision_row(group, for_update=True)
        row = MissionControlGroupLeasePolicy.objects.select_for_update().filter(group=group).first()
        actual = _current_revision(revision_row, row)
        if expected != actual:
            raise _error(
                MissionControlLeasePolicyAdminError.Kind.REVISION_CONFLICT,
                "Mission Control group lease policy changed; refresh and try again",
            )
        if row is not None and _policy_from_row(row) == canonical:
            return _override_from_row(row)
        previous = _policy_state(_policy_from_row(row), row.revision, scope="group", group_id=group.pk) if row else None
        next_revision = _advance_revision(revision_row, actual=actual, group=group)
        if row is None:
            row = MissionControlGroupLeasePolicy.objects.create(
                group=group,
                **canonical.model_dump(),
                revision=next_revision,
            )
        else:
            for field, value in canonical.model_dump().items():
                setattr(row, field, value)
            row.revision = next_revision
            row.save(
                update_fields=[
                    "initial_days",
                    "extension_days",
                    "maximum_days",
                    "extensions_enabled",
                    "revision",
                    "updated_at",
                ]
            )
        _write_audit(
            entity_id=group.pk,
            context="mission_control_group_lease_policy",
            audit=audit,
            previous=previous,
            current=_policy_state(canonical, row.revision, scope="group", group_id=group.pk),
        )
        return _override_from_row(row)


def reset_group_lease_policy(
    actor: User,
    group_id: int,
    *,
    expected_revision: int,
    audit: LeasePolicyAuditContext,
) -> None:
    """Remove one eligible-group override under revision CAS."""
    _assert_active_superuser(actor)
    expected = _expected_revision(expected_revision)
    with transaction.atomic():
        _lock_policy_namespace()
        _effective_tenant(for_update=True)
        group = _eligible_group_for_update(group_id)
        revision_row = _group_revision_row(group, for_update=True)
        row = MissionControlGroupLeasePolicy.objects.select_for_update().filter(group=group).first()
        actual = _current_revision(revision_row, row)
        if expected != actual:
            raise _error(
                MissionControlLeasePolicyAdminError.Kind.REVISION_CONFLICT,
                "Mission Control group lease policy changed; refresh and try again",
            )
        if row is None:
            return
        previous = _policy_state(_policy_from_row(row), row.revision, scope="group", group_id=group.pk)
        next_revision = _advance_revision(revision_row, actual=actual, group=group)
        _write_audit(
            entity_id=group.pk,
            context="mission_control_group_lease_policy_reset",
            audit=audit,
            previous=previous,
            current={"scope": "group", "group_id": group.pk, "source": "tenant", "revision": next_revision},
        )
        row.delete()


__all__ = [
    "LeasePolicyAuditContext",
    "LeasePolicyGroupRevision",
    "LeasePolicyGroupSettings",
    "LeasePolicyOverride",
    "MissionControlLeasePolicyAdminError",
    "MissionControlLeasePolicySettings",
    "ResolvedMissionControlLeasePolicy",
    "get_mission_control_lease_settings",
    "replace_group_lease_policy",
    "replace_tenant_lease_policy",
    "reset_group_lease_policy",
    "reset_tenant_lease_policy",
    "resolve_mission_control_lease_policy",
]
