"""Behavior tests for the workspace resource-quota service (PLAT-239, issue #1946).

Drives the real service against real rows. Each authority/enforcement test asks
the seam a question a caller would ask and asserts the effect (allowed / denied /
persisted / blocked), so it goes red if the enforcement is removed — not that a
helper was called.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from shared.audit import AuditAction
from shared.models import AuditLog
from workspaces import services
from workspaces.models import (
    QUOTA_MODE_ADVISORY,
    QUOTA_MODE_ENFORCING,
    QUOTA_OUTCOME_REJECTED,
    QUOTA_OUTCOME_WARNED,
    QUOTA_RESOURCE_CONCURRENT_RANGES,
    QUOTA_RESOURCE_MEMBER_SEATS,
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
    WorkspaceQuotaDecision,
    WorkspaceQuotaPolicy,
    WorkspaceQuotaReservation,
)
from workspaces.roles import OrganizationRole, WorkspaceRole

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user(suffix, *, is_superuser=False):
    return User.objects.create_user(
        username=f"wq-{suffix}@e.com",
        email=f"wq-{suffix}@e.com",
        is_superuser=is_superuser,
        is_staff=is_superuser,
    )


def _org(name="Quota Org"):
    return Organization.objects.create(name=name)


def _org_admin(organization, suffix="admin"):
    actor = _user(suffix)
    OrganizationMembership.objects.create(organization=organization, user=actor, role=OrganizationRole.ADMIN.value)
    return actor


def _audit(actor):
    return services.WorkspaceQuotaAuditContext(actor_type="user", actor_id=getattr(actor, "pk", None))


def _member_audit(actor):
    return services.MembershipAuditContext(actor_type="user", actor_id=getattr(actor, "pk", None))


def _workspace(owner):
    """Create a shared workspace owned by ``owner`` (seeds one OWNER seat)."""
    workspace = Workspace.objects.create(organization=_org(), name="Team")
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role=WorkspaceRole.OWNER.value)
    return workspace


def test_model_repr_strings_are_diagnostic():
    workspace = _workspace(_user("owner"))
    policy = WorkspaceQuotaPolicy.objects.create(
        workspace=workspace, resource=QUOTA_RESOURCE_MEMBER_SEATS, limit=3, mode=QUOTA_MODE_ENFORCING
    )
    decision = WorkspaceQuotaDecision.objects.create(
        workspace=workspace,
        resource=QUOTA_RESOURCE_MEMBER_SEATS,
        limit_at_decision=3,
        mode_at_decision=QUOTA_MODE_ENFORCING,
        policy_revision=1,
        usage_before=3,
        outcome=QUOTA_OUTCOME_REJECTED,
        reason_code="hard_cap_exhausted",
    )
    reservation = WorkspaceQuotaReservation.objects.create(
        workspace=workspace, resource=QUOTA_RESOURCE_CONCURRENT_RANGES, correlation_key="corr-1"
    )
    assert "member_seats" in str(policy)
    assert "member_seats" in str(decision)
    assert "open" in str(reservation)


# ---------------------------------------------------------------------------
# Policy authoring authority (superuser-only composition-root)
# ---------------------------------------------------------------------------


def test_superuser_sets_quota_policy_and_bumps_revision_on_change():
    superuser = _user("root", is_superuser=True)
    owner = _user("owner")
    workspace = _workspace(owner)

    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 5, QUOTA_MODE_ENFORCING, audit=_audit(superuser)
    )
    policy = WorkspaceQuotaPolicy.objects.get(workspace=workspace, resource=QUOTA_RESOURCE_MEMBER_SEATS)
    assert policy.limit == 5
    assert policy.mode == QUOTA_MODE_ENFORCING
    assert policy.revision == 1

    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 8, QUOTA_MODE_ADVISORY, audit=_audit(superuser)
    )
    policy.refresh_from_db()
    assert policy.limit == 8
    assert policy.mode == QUOTA_MODE_ADVISORY
    assert policy.revision == 2


def test_setting_unchanged_policy_is_a_noop_without_audit():
    superuser = _user("root", is_superuser=True)
    workspace = _workspace(_user("owner"))
    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 5, QUOTA_MODE_ENFORCING, audit=_audit(superuser)
    )
    baseline = AuditLog.objects.count()

    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 5, QUOTA_MODE_ENFORCING, audit=_audit(superuser)
    )
    assert WorkspaceQuotaPolicy.objects.get(workspace=workspace).revision == 1
    assert AuditLog.objects.count() == baseline


def test_non_superuser_owner_cannot_set_quota_policy():
    owner = _user("owner")
    workspace = _workspace(owner)
    audit = _audit(owner)
    with pytest.raises(services.WorkspaceQuotaError) as excinfo:
        services.set_workspace_quota_policy(
            owner, workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 5, QUOTA_MODE_ENFORCING, audit=audit
        )
    assert excinfo.value.code == "quota_policy_forbidden"
    assert not WorkspaceQuotaPolicy.objects.exists()


def test_org_admin_without_superuser_cannot_set_quota_policy():
    organization = _org()
    admin = _org_admin(organization)
    workspace = Workspace.objects.create(organization=organization, name="Team")
    WorkspaceMembership.objects.create(workspace=workspace, user=admin, role=WorkspaceRole.OWNER.value)
    audit = _audit(admin)
    with pytest.raises(services.WorkspaceQuotaError) as excinfo:
        services.set_workspace_quota_policy(
            admin, workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 5, QUOTA_MODE_ENFORCING, audit=audit
        )
    assert excinfo.value.code == "quota_policy_forbidden"


@pytest.mark.parametrize(
    ("resource", "limit", "mode", "code"),
    [
        ("bogus_resource", 5, QUOTA_MODE_ENFORCING, "quota_resource_invalid"),
        (QUOTA_RESOURCE_MEMBER_SEATS, 5, "loose", "quota_mode_invalid"),
        (QUOTA_RESOURCE_MEMBER_SEATS, -1, QUOTA_MODE_ENFORCING, "quota_limit_invalid"),
        (QUOTA_RESOURCE_MEMBER_SEATS, True, QUOTA_MODE_ENFORCING, "quota_limit_invalid"),
    ],
)
def test_set_quota_policy_rejects_invalid_input(resource, limit, mode, code):
    superuser = _user("root", is_superuser=True)
    workspace = _workspace(_user("owner"))
    audit = _audit(superuser)
    with pytest.raises(services.WorkspaceQuotaError) as excinfo:
        services.set_workspace_quota_policy(superuser, workspace.uuid, resource, limit, mode, audit=audit)
    assert excinfo.value.code == code


# ---------------------------------------------------------------------------
# Usage read (READ_WORKSPACE: owner/admin only)
# ---------------------------------------------------------------------------


def test_owner_reads_usage_against_limits():
    superuser = _user("root", is_superuser=True)
    owner = _user("owner")
    workspace = _workspace(owner)
    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 3, QUOTA_MODE_ENFORCING, audit=_audit(superuser)
    )

    projection = services.workspace_quota_usage(owner, workspace.uuid)

    seats = next(r for r in projection.resources if r.resource == QUOTA_RESOURCE_MEMBER_SEATS)
    ranges = next(r for r in projection.resources if r.resource == QUOTA_RESOURCE_CONCURRENT_RANGES)
    assert seats.usage == 1  # the owner seat
    assert seats.limit == 3
    assert seats.mode == QUOTA_MODE_ENFORCING
    assert ranges.limit is None  # unconfigured -> unlimited


def test_plain_member_cannot_read_quota_usage():
    owner = _user("owner")
    member = _user("member")
    workspace = _workspace(owner)
    WorkspaceMembership.objects.create(workspace=workspace, user=member, role=WorkspaceRole.MEMBER.value)
    with pytest.raises(services.WorkspaceAuthorizationError):
        services.workspace_quota_usage(member, workspace.uuid)


def test_non_member_cannot_read_quota_usage():
    owner = _user("owner")
    workspace = _workspace(owner)
    outsider = _user("outsider")
    with pytest.raises(services.WorkspaceAuthorizationError):
        services.workspace_quota_usage(outsider, workspace.uuid)


# ---------------------------------------------------------------------------
# Member-seat enforcement (direct add + invitation acceptance)
# ---------------------------------------------------------------------------


def test_enforcing_seat_cap_blocks_add_and_records_rejection():
    superuser = _user("root", is_superuser=True)
    owner = _user("owner")
    workspace = _workspace(owner)  # 1 seat (owner)
    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 1, QUOTA_MODE_ENFORCING, audit=_audit(superuser)
    )
    target = _user("newbie")
    audit = _member_audit(owner)

    with pytest.raises(services.WorkspaceMembershipError) as excinfo:
        services.add_workspace_member(owner, workspace.uuid, target.email, WorkspaceRole.MEMBER.value, audit=audit)

    assert excinfo.value.code == "workspace_member_seats_exhausted"
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=target).exists()
    rejection = WorkspaceQuotaDecision.objects.get(workspace=workspace, resource=QUOTA_RESOURCE_MEMBER_SEATS)
    assert rejection.outcome == QUOTA_OUTCOME_REJECTED
    assert rejection.usage_before == 1
    assert AuditLog.objects.filter(action=AuditAction.QUOTA_APPLIED.value).exists()


def test_advisory_seat_cap_admits_but_warns_and_records():
    superuser = _user("root", is_superuser=True)
    owner = _user("owner")
    workspace = _workspace(owner)
    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 1, QUOTA_MODE_ADVISORY, audit=_audit(superuser)
    )
    target = _user("newbie")

    services.add_workspace_member(
        owner, workspace.uuid, target.email, WorkspaceRole.MEMBER.value, audit=_member_audit(owner)
    )

    assert WorkspaceMembership.objects.filter(workspace=workspace, user=target).exists()
    warned = WorkspaceQuotaDecision.objects.get(workspace=workspace, resource=QUOTA_RESOURCE_MEMBER_SEATS)
    assert warned.outcome == QUOTA_OUTCOME_WARNED


def test_add_within_seat_limit_records_admitted_decision():
    superuser = _user("root", is_superuser=True)
    owner = _user("owner")
    workspace = _workspace(owner)
    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 5, QUOTA_MODE_ENFORCING, audit=_audit(superuser)
    )
    target = _user("newbie")

    services.add_workspace_member(
        owner, workspace.uuid, target.email, WorkspaceRole.MEMBER.value, audit=_member_audit(owner)
    )

    assert WorkspaceMembership.objects.filter(workspace=workspace, user=target).count() == 1
    decision = WorkspaceQuotaDecision.objects.get(workspace=workspace, resource=QUOTA_RESOURCE_MEMBER_SEATS)
    assert decision.outcome == "admitted"
    assert decision.usage_before == 1


def test_unlimited_seats_when_no_policy_records_no_decision():
    owner = _user("owner")
    workspace = _workspace(owner)
    target = _user("newbie")

    services.add_workspace_member(
        owner, workspace.uuid, target.email, WorkspaceRole.MEMBER.value, audit=_member_audit(owner)
    )

    assert WorkspaceMembership.objects.filter(workspace=workspace, user=target).exists()
    assert not WorkspaceQuotaDecision.objects.filter(workspace=workspace).exists()


def test_idempotent_re_add_does_not_consume_a_seat_or_decide():
    superuser = _user("root", is_superuser=True)
    owner = _user("owner")
    workspace = _workspace(owner)
    target = _user("newbie")
    services.add_workspace_member(
        owner, workspace.uuid, target.email, WorkspaceRole.MEMBER.value, audit=_member_audit(owner)
    )
    # Lock the seat count at exactly the current membership total.
    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 2, QUOTA_MODE_ENFORCING, audit=_audit(superuser)
    )

    # Re-adding the same account at the same role is idempotent: no new seat, no
    # rejection, even though usage already equals the limit.
    services.add_workspace_member(
        owner, workspace.uuid, target.email, WorkspaceRole.MEMBER.value, audit=_member_audit(owner)
    )
    assert WorkspaceMembership.objects.filter(workspace=workspace, user=target).count() == 1
    assert not WorkspaceQuotaDecision.objects.filter(workspace=workspace, outcome=QUOTA_OUTCOME_REJECTED).exists()


# ---------------------------------------------------------------------------
# Concurrent-range reservation primitives
# ---------------------------------------------------------------------------


def test_reserve_creates_open_reservation_and_release_is_idempotent():
    superuser = _user("root", is_superuser=True)
    workspace = _workspace(_user("owner"))
    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_CONCURRENT_RANGES, 2, QUOTA_MODE_ENFORCING, audit=_audit(superuser)
    )

    verdict = services.reserve_workspace_concurrent_range(workspace.pk, "corr-1", _audit(superuser))
    assert verdict.outcome == "admitted"
    assert WorkspaceQuotaReservation.objects.filter(
        workspace=workspace, correlation_key="corr-1", released_at__isnull=True
    ).exists()

    # Replay is idempotent: no second open reservation.
    services.reserve_workspace_concurrent_range(workspace.pk, "corr-1", _audit(superuser))
    assert WorkspaceQuotaReservation.objects.filter(workspace=workspace, correlation_key="corr-1").count() == 1

    assert services.release_workspace_concurrent_range(workspace.pk, "corr-1") is True
    assert services.release_workspace_concurrent_range(workspace.pk, "corr-1") is False


def test_enforcing_concurrent_range_cap_rejects_over_limit():
    superuser = _user("root", is_superuser=True)
    workspace = _workspace(_user("owner"))
    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_CONCURRENT_RANGES, 1, QUOTA_MODE_ENFORCING, audit=_audit(superuser)
    )
    audit = _audit(superuser)
    services.reserve_workspace_concurrent_range(workspace.pk, "corr-1", audit)

    with pytest.raises(services.WorkspaceQuotaRejected) as excinfo:
        services.reserve_workspace_concurrent_range(workspace.pk, "corr-2", audit)
    assert excinfo.value.verdict.outcome == QUOTA_OUTCOME_REJECTED
    assert excinfo.value.workspace_id == workspace.pk
    # The rejected reservation was not created.
    assert not WorkspaceQuotaReservation.objects.filter(workspace=workspace, correlation_key="corr-2").exists()


def test_advisory_concurrent_range_cap_warns_but_reserves():
    superuser = _user("root", is_superuser=True)
    workspace = _workspace(_user("owner"))
    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_CONCURRENT_RANGES, 1, QUOTA_MODE_ADVISORY, audit=_audit(superuser)
    )
    services.reserve_workspace_concurrent_range(workspace.pk, "corr-1", _audit(superuser))

    verdict = services.reserve_workspace_concurrent_range(workspace.pk, "corr-2", _audit(superuser))
    assert verdict.outcome == QUOTA_OUTCOME_WARNED
    assert WorkspaceQuotaReservation.objects.filter(
        workspace=workspace, correlation_key="corr-2", released_at__isnull=True
    ).exists()


def test_released_reservation_frees_capacity_for_a_new_launch():
    superuser = _user("root", is_superuser=True)
    workspace = _workspace(_user("owner"))
    services.set_workspace_quota_policy(
        superuser, workspace.uuid, QUOTA_RESOURCE_CONCURRENT_RANGES, 1, QUOTA_MODE_ENFORCING, audit=_audit(superuser)
    )
    services.reserve_workspace_concurrent_range(workspace.pk, "corr-1", _audit(superuser))
    services.release_workspace_concurrent_range(workspace.pk, "corr-1")

    # Freed slot admits a new, differently-keyed launch.
    verdict = services.reserve_workspace_concurrent_range(workspace.pk, "corr-2", _audit(superuser))
    assert verdict.outcome == "admitted"
