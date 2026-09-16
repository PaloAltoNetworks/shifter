"""Tests for cms.services query helpers.

Covers get_range_target_instances, which selects the instances shown on the
CTF participant range page. Explicit scenario ``participant_access`` bindings
are authoritative: POLARIS exposes the Kali workstation, not the DC. A
single-seat lab that provisions only an attacker-tagged seat must still show it.

The selector reads the user's ready range from the engine, so these exercise
the real database rather than mocking the first-party query seam (ADR-019-R1):
each case seeds an engine ``Range`` and asserts what the selector returns.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from cms.services import get_range_target_instances

User = get_user_model()

_ATTACKER = {
    "name": "single-seat-lab",
    "role": "attacker",
    "os_type": "kali",
    "private_ip": "10.1.2.22",
    "uuid": "aaaa",
}
_POLARIS_KALI = {
    **_ATTACKER,
    "name": "kali",
    "participant_access_channels": ["ssh", "rdp"],
}
_AWS_POLARIS_KALI = {
    **_ATTACKER,
    "name": "kali",
    "cloud_provider": "aws",
    "participant_access_channels": None,
}
_DC = {
    "name": "dc01",
    "role": "dc",
    "os_type": "windows",
    "private_ip": "10.1.2.30",
    "uuid": "bbbb",
}


@pytest.fixture
def user(db):
    return User.objects.create_user(username="queries@example.com", email="queries@example.com")


def _ready_range(user, provisioned_instances, *, workspace_id=None, range_source=None):
    """Seed a correlated ready CMS/Engine range."""
    from cms.models import RangeInstance
    from cms.models import Request as CMSRequest
    from engine.models import Range as EngineRange
    from engine.models import Request as EngineRequest
    from shared.enums import RangeSource, RequestType, ResourceStatus
    from workspaces.services import resolve_personal_workspace

    workspace_id = workspace_id or resolve_personal_workspace(user).workspace_id
    range_source = range_source or RangeSource.CTF.value
    request_id = uuid4()
    cms_request = CMSRequest.objects.create(
        workspace_id=workspace_id,
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=user,
    )
    engine_request = EngineRequest.objects.create(
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=user,
    )
    cms_range = RangeInstance.objects.create(
        workspace_id=workspace_id,
        request=cms_request,
        user_id=user.pk,
        scenario_id="test",
        status=ResourceStatus.READY.value,
        range_source=range_source,
    )
    engine_range = EngineRange.objects.create(
        workspace_id=workspace_id,
        user=user,
        request=engine_request,
        status=EngineRange.Status.READY,
        provisioned_instances=provisioned_instances,
    )
    return cms_range, engine_range


class TestGetRangeTargetInstances:
    """Behavior of the CTF range-page instance selector."""

    def test_explicit_participant_access_returns_declared_target(self, user):
        """POLARIS-style range: the declared Kali workstation is the user target."""
        _ready_range(user, [_POLARIS_KALI, _DC])
        assert get_range_target_instances(user) == [_POLARIS_KALI]

    def test_aws_open_access_returns_attacker_seat(self, user):
        """AWS POLARIS state exposes the Kali seat when no closed binding exists."""
        _ready_range(user, [_AWS_POLARIS_KALI, _DC])
        assert get_range_target_instances(user) == [_AWS_POLARIS_KALI]

    def test_legacy_multi_node_hides_attacker_and_shows_targets(self, user):
        """Legacy rows without access channels keep the non-attacker heuristic."""
        _ready_range(user, [_ATTACKER, _DC])
        assert get_range_target_instances(user) == [_DC]

    def test_single_seat_lab_returns_attacker_seat(self, user):
        """The sole attacker-tagged seat is returned."""
        _ready_range(user, [_ATTACKER])
        assert get_range_target_instances(user) == [_ATTACKER]

    def test_no_ready_range_returns_empty(self, user):
        """No ready range / no instances yields an empty list."""
        assert get_range_target_instances(user) == []

    def test_membership_removal_revokes_targets(self, user):
        from workspaces.models import WorkspaceMembership

        _ready_range(user, [_POLARIS_KALI])
        WorkspaceMembership.objects.filter(user=user).delete()

        assert get_range_target_instances(user) == []

    def test_ctf_range_is_correlated_to_projected_engine_range(self, user):
        from shared.enums import RangeSource
        from workspaces.models import Organization, Workspace, WorkspaceMembership
        from workspaces.roles import WorkspaceRole

        _personal_range, personal_engine_range = _ready_range(
            user,
            [{**_DC, "name": "mission-control-range"}],
            range_source=RangeSource.MISSION_CONTROL.value,
        )
        organization = Organization.objects.create(name="Shared organization")
        shared_workspace = Workspace.objects.create(organization=organization, name="Shared workspace")
        WorkspaceMembership.objects.create(
            workspace=shared_workspace,
            user=user,
            role=WorkspaceRole.MEMBER,
        )
        _ready_range(
            user,
            [{**_POLARIS_KALI, "name": "authorized-range"}],
            workspace_id=shared_workspace.pk,
        )
        type(personal_engine_range).objects.filter(pk=personal_engine_range.pk).update(
            created_at=timezone.now() + timedelta(minutes=1)
        )

        assert get_range_target_instances(user) == [{**_POLARIS_KALI, "name": "authorized-range"}]
