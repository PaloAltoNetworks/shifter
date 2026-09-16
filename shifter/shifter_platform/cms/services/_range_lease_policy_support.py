"""Persistence helpers and projections for Mission Control lease policy (#2169)."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.contrib.auth.models import Group
from django.db import connection
from pydantic import ValidationError

from cms.exceptions import CMSError
from cms.models import (
    MissionControlGroupLeasePolicy,
    MissionControlGroupLeasePolicyRevision,
    MissionControlTenantLeasePolicy,
    MissionControlTenantLeasePolicyRevision,
)
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from shared.auth import CTF_PARTICIPANT_GROUP
from shared.mission_control_lease import MissionControlLeasePolicy

if TYPE_CHECKING:
    from django.contrib.auth.models import User

# A transaction-scoped PostgreSQL mutex closes the absent-singleton race that a
# SELECT FOR UPDATE cannot cover. SQLite is used for fast behavioral tests and
# serializes writes itself; PostgreSQL concurrency coverage proves this mutex.
_ADVISORY_LOCK_NAMESPACE = 0x53484654
_ADVISORY_LOCK_KEY = 2169
_INELIGIBLE_GROUP_NAMES = frozenset({CTF_PARTICIPANT_GROUP})


class MissionControlLeasePolicyAdminError(CMSError):
    """Classified, bounded runtime lease-policy administration outcome."""

    class Kind(enum.Enum):
        """Stable categories exposed through the administrator API."""

        FORBIDDEN = "forbidden"
        INVALID_POLICY = "invalid_policy"
        REVISION_CONFLICT = "revision_conflict"
        GROUP_NOT_FOUND = "group_not_found"
        GROUP_INELIGIBLE = "group_ineligible"
        CHILD_POLICY_CONFLICT = "child_policy_conflict"

    def __init__(self, kind: MissionControlLeasePolicyAdminError.Kind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class LeasePolicyAuditContext:
    """Trusted request attribution passed into strict-audited commands."""

    actor_type: str
    actor_id: int | None
    request_id: str = ""
    source_ip: str | None = None
    user_agent: str = ""


@dataclass(frozen=True, slots=True)
class LeasePolicyOverride:
    """One persisted complete policy and its compare-and-set revision."""

    policy: MissionControlLeasePolicy
    revision: int


@dataclass(frozen=True, slots=True)
class LeasePolicyGroupRevision:
    """Bounded group-policy provenance for an effective resolution."""

    group_id: int
    revision: int


@dataclass(frozen=True, slots=True)
class ResolvedMissionControlLeasePolicy:
    """Canonical policy plus bounded source/revision provenance."""

    policy: MissionControlLeasePolicy
    source: str
    tenant_revision: int
    group_revisions: tuple[LeasePolicyGroupRevision, ...]


@dataclass(frozen=True, slots=True)
class LeasePolicyGroupSettings:
    """Admin projection for one policy-eligible Django group."""

    group_id: int
    group_name: str
    revision: int
    override: LeasePolicyOverride | None


@dataclass(frozen=True, slots=True)
class MissionControlLeasePolicySettings:
    """Admin settings projection with visible fallback/override precedence."""

    baseline: MissionControlLeasePolicy
    tenant_revision: int
    tenant_override: LeasePolicyOverride | None
    effective_tenant: MissionControlLeasePolicy
    effective_source: str
    groups: tuple[LeasePolicyGroupSettings, ...]


def _error(kind: MissionControlLeasePolicyAdminError.Kind, message: str) -> MissionControlLeasePolicyAdminError:
    """Build a classified service error with a bounded internal message."""
    return MissionControlLeasePolicyAdminError(kind, message)


def _assert_active_superuser(actor: User) -> None:
    """Require the service caller to be an authenticated active superuser."""
    if not (
        getattr(actor, "is_authenticated", False)
        and getattr(actor, "is_active", False)
        and getattr(actor, "is_superuser", False)
    ):
        raise _error(
            MissionControlLeasePolicyAdminError.Kind.FORBIDDEN,
            "Only an active platform superuser may administer Mission Control lease policy",
        )


def _deployment_policy() -> MissionControlLeasePolicy:
    """Return the validated deployment fallback policy."""
    from django.conf import settings

    # Runtime composition already validates this value. Re-validating the object
    # preserves a fail-closed service boundary for test/alternate callers.
    return _canonical_policy(settings.MISSION_CONTROL_LEASE_POLICY)


def _canonical_policy(policy: object) -> MissionControlLeasePolicy:
    """Validate any boundary value through the shared canonical contract."""
    try:
        if isinstance(policy, MissionControlLeasePolicy):
            return MissionControlLeasePolicy.model_validate(policy.model_dump())
        return MissionControlLeasePolicy.model_validate(policy)
    except (TypeError, ValidationError) as exc:
        raise _error(
            MissionControlLeasePolicyAdminError.Kind.INVALID_POLICY,
            "Mission Control lease policy is invalid",
        ) from exc


def _policy_from_row(
    row: MissionControlTenantLeasePolicy | MissionControlGroupLeasePolicy,
) -> MissionControlLeasePolicy:
    """Convert a typed policy row into the canonical policy contract."""
    return _canonical_policy(
        {
            "initial_days": row.initial_days,
            "extension_days": row.extension_days,
            "maximum_days": row.maximum_days,
            "extensions_enabled": row.extensions_enabled,
        }
    )


def _override_from_row(
    row: MissionControlTenantLeasePolicy | MissionControlGroupLeasePolicy,
) -> LeasePolicyOverride:
    """Project a persisted row as a policy plus revision."""
    return LeasePolicyOverride(policy=_policy_from_row(row), revision=row.revision)


def _policy_state(policy: MissionControlLeasePolicy, revision: int, **extra: object) -> dict[str, object]:
    """Build the bounded scalar policy state written to strict audit."""
    return {
        **extra,
        **policy.model_dump(),
        "revision": revision,
    }


def _expected_revision(value: object) -> int:
    """Validate a compare-and-set revision without accepting boolean coercion."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _error(
            MissionControlLeasePolicyAdminError.Kind.INVALID_POLICY,
            "Expected revision must be a non-negative integer",
        )
    return value


def _lock_policy_namespace() -> None:
    """Serialize authoritative policy reads and writes on PostgreSQL."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                [_ADVISORY_LOCK_NAMESPACE, _ADVISORY_LOCK_KEY],
            )


def _tenant_row(*, for_update: bool) -> MissionControlTenantLeasePolicy | None:
    """Read the optional tenant override, locking it when requested."""
    rows = (
        MissionControlTenantLeasePolicy.objects.select_for_update()
        if for_update
        else MissionControlTenantLeasePolicy.objects.all()
    )
    return rows.filter(pk=1).first()


def _tenant_revision_row(*, for_update: bool) -> MissionControlTenantLeasePolicyRevision | None:
    """Read the durable tenant revision fence, locking it when requested."""
    rows = (
        MissionControlTenantLeasePolicyRevision.objects.select_for_update()
        if for_update
        else MissionControlTenantLeasePolicyRevision.objects.all()
    )
    return rows.filter(pk=1).first()


def _group_revision_row(
    group: Group,
    *,
    for_update: bool,
) -> MissionControlGroupLeasePolicyRevision | None:
    """Read a group's durable revision fence, locking it when requested."""
    rows = (
        MissionControlGroupLeasePolicyRevision.objects.select_for_update()
        if for_update
        else MissionControlGroupLeasePolicyRevision.objects.all()
    )
    return rows.filter(group=group).first()


def _current_revision(
    revision_row: MissionControlTenantLeasePolicyRevision | MissionControlGroupLeasePolicyRevision | None,
    policy_row: MissionControlTenantLeasePolicy | MissionControlGroupLeasePolicy | None,
) -> int:
    """Resolve the durable revision, including backward-compatible policy rows."""
    if revision_row is not None:
        return revision_row.revision
    return policy_row.revision if policy_row is not None else 0


def _advance_revision(
    revision_row: MissionControlTenantLeasePolicyRevision | MissionControlGroupLeasePolicyRevision | None,
    *,
    actual: int,
    group: Group | None = None,
) -> int:
    """Advance and persist a scope revision so reset cannot create an ABA gap."""
    next_revision = actual + 1
    if revision_row is None:
        if group is None:
            MissionControlTenantLeasePolicyRevision.objects.create(revision=next_revision)
        else:
            MissionControlGroupLeasePolicyRevision.objects.create(group=group, revision=next_revision)
    else:
        revision_row.revision = next_revision
        revision_row.save(update_fields=["revision", "updated_at"])
    return next_revision


def _effective_tenant(*, for_update: bool) -> tuple[MissionControlLeasePolicy, int, str]:
    """Resolve the runtime tenant override or the deployment fallback."""
    row = _tenant_row(for_update=for_update)
    if row is None:
        return _deployment_policy(), 0, "deployment"
    return _policy_from_row(row), row.revision, "runtime"


def _matching_group_rows(user: User, *, for_update: bool) -> list[MissionControlGroupLeasePolicy]:
    """Read eligible persisted policies for the user's committed RBAC groups."""
    user_id = getattr(user, "pk", None)
    if user_id is None:
        return []
    group_ids = list(user.groups.exclude(name__in=_INELIGIBLE_GROUP_NAMES).order_by("pk").values_list("pk", flat=True))
    rows = MissionControlGroupLeasePolicy.objects.filter(group_id__in=group_ids).select_related("group")
    if for_update:
        rows = rows.select_for_update()
    return list(rows.order_by("group_id"))


def _validate_children(maximum_days: int, rows: list[MissionControlGroupLeasePolicy]) -> None:
    """Reject a tenant maximum that would invalidate a persisted group policy."""
    if any(row.initial_days > maximum_days or row.maximum_days > maximum_days for row in rows):
        raise _error(
            MissionControlLeasePolicyAdminError.Kind.CHILD_POLICY_CONFLICT,
            "A group lease policy exceeds the proposed tenant maximum",
        )


def _write_audit(
    *,
    entity_id: int,
    context: str,
    audit: LeasePolicyAuditContext,
    previous: dict[str, object] | None,
    current: dict[str, object],
) -> None:
    """Write policy mutation state through the strict audit boundary."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=entity_id,
            action=AuditAction.UPDATE,
            actor_type=audit.actor_type,
            actor_id=audit.actor_id,
            previous_state=previous,
            new_state=current,
            context=context,
            source_ip=audit.source_ip,
            user_agent=audit.user_agent[:500],
            request_id=audit.request_id[:64],
        ),
        strict=True,
    )


def _eligible_group_for_update(group_id: int) -> Group:
    """Lock and return an administrator-controlled policy-eligible group."""
    group = Group.objects.select_for_update().filter(pk=group_id).first()
    if group is None:
        raise _error(MissionControlLeasePolicyAdminError.Kind.GROUP_NOT_FOUND, "Group not found")
    if group.name in _INELIGIBLE_GROUP_NAMES:
        raise _error(
            MissionControlLeasePolicyAdminError.Kind.GROUP_INELIGIBLE,
            "This group is not eligible for Mission Control lease policy",
        )
    return group
