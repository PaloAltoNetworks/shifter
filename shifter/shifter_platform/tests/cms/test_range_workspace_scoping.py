"""Cross-workspace denial across every interactive range lifecycle surface (#1327).

Acceptance criterion: "Authorization tests cover cross-workspace denial for each
lifecycle surface." Each test drives a real ``RangeInstance`` (with its Engine
Range/Request rows) created by the ``provision_range`` fixture, then strands the
range in a workspace the owner is not a member of -- exactly what a membership
removal leaves behind -- and proves the surface denies before any status write,
Engine dispatch, or secret retrieval. Authorization is conjunctive (ADR-046-R8):
owning the range is necessary but not sufficient; a permitting workspace role is
also required, and a workspace role never shares another member's range.
"""

from __future__ import annotations

import pytest

from cms import services
from cms.exceptions import CMSError
from engine.models import Range as EngineRange
from workspaces.models import Organization, Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="ws-scope@e.com", email="ws-scope@e.com")


def _set_scope(range_instance, workspace_id: int) -> None:
    """Move all three ownership projections onto ``workspace_id`` for test setup."""
    range_instance.workspace_id = workspace_id
    range_instance.save(update_fields=["workspace_id"])
    request = range_instance.request
    request.workspace_id = workspace_id
    request.save(update_fields=["workspace_id"])
    EngineRange.objects.filter(request__request_id=request.request_id).update(workspace_id=workspace_id)


def _strand_outside_membership(range_instance) -> Workspace:
    """Bind the range to a workspace the owner has no membership in (a revoked scope)."""
    organization = Organization.objects.create(name="Stranded Org")
    workspace = Workspace.objects.create(organization=organization, name="Stranded")
    _set_scope(range_instance, workspace.id)
    return workspace


def test_query_surfaces_omit_or_deny_a_stranded_range(provision_range, user):
    range_instance = provision_range(user)
    request_id = str(range_instance.request.request_id)
    _strand_outside_membership(range_instance)

    assert services.get_active_range(user) is None
    assert services.list_ranges(user) == []
    assert services.list_mission_control_range_history(user) == []
    assert services.has_ready_active_range(user) is False
    with pytest.raises(CMSError):
        services.get_range(user, range_instance.range_id)
    with pytest.raises(CMSError):
        services.get_range_by_request_id(user, request_id)


@pytest.mark.parametrize("service_name", ["pause_range", "resume_range", "destroy_range"])
def test_lifecycle_mutations_deny_a_stranded_range_before_any_status_write(provision_range, user, service_name):
    range_instance = provision_range(user)
    status_before = range_instance.status
    _strand_outside_membership(range_instance)
    service = getattr(services, service_name)

    with pytest.raises(CMSError):
        service(user, range_instance.pk)

    range_instance.refresh_from_db()
    assert range_instance.status == status_before


@pytest.mark.parametrize(
    "service_name",
    ["pause_range_by_request_id", "resume_range_by_request_id", "destroy_range_by_request_id"],
)
def test_lifecycle_by_request_id_denies_a_stranded_range(provision_range, user, service_name):
    range_instance = provision_range(user)
    request_id = str(range_instance.request.request_id)
    _strand_outside_membership(range_instance)
    service = getattr(services, service_name)

    with pytest.raises(CMSError):
        service(user, request_id)


def test_remote_access_and_lease_deny_a_stranded_range(provision_range, user):
    from cms.services import OpenVpnProfileNotFound, RangeLeaseNotFound

    range_instance = provision_range(user)
    _strand_outside_membership(range_instance)

    with pytest.raises(OpenVpnProfileNotFound):
        services.get_mission_control_openvpn_profile(user)
    assert services.get_mission_control_range_lease(user) is None
    with pytest.raises(RangeLeaseNotFound):
        services.extend_mission_control_range(user)


def test_a_workspace_teammate_still_cannot_use_the_owners_range(provision_range, user, django_user_model):
    """Membership authorizes the workspace, not another member's range (ADR-046-R8)."""
    range_instance = provision_range(user)
    organization = Organization.objects.create(name="Team Org")
    workspace = Workspace.objects.create(organization=organization, name="Team")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role=WorkspaceRole.OWNER.value)
    teammate = django_user_model.objects.create_user(username="teammate@e.com", email="teammate@e.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=teammate, role=WorkspaceRole.MEMBER.value)
    _set_scope(range_instance, workspace.id)

    # The owner, who is also a member, still reaches the range.
    assert services.get_range(user, range_instance.range_id).range_id == range_instance.range_id
    # The teammate shares the workspace but does not own the range.
    with pytest.raises(CMSError):
        services.get_range(teammate, range_instance.range_id)
    assert services.list_ranges(teammate) == []
