"""Model-access composition over CMS-owned canonical Engine range identities."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from cms import services as cms_services
from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from config.model_access_sharing import ModelAccessCompositionError, resolve_model_access_selector
from ctf.enums import EventStatus, ParticipantStatus
from ctf.models import CTFEvent, CTFParticipant
from engine.models import Range
from engine.models import Request as EngineRequest
from management import services as management_services
from shared.enums import RequestType
from shared.model_access import PublisherAuthorityScope, SelectorKind, SharingSelector
from workspaces.models import Organization, OrganizationMembership, Workspace, WorkspaceMembership
from workspaces.roles import OrganizationRole, WorkspaceRole

pytestmark = pytest.mark.django_db

User = get_user_model()


def _operator():
    return User.objects.create_superuser("operator@test", "operator@test", "unused")


def _range(owner, workspace, status=Range.Status.READY):
    return Range.objects.create(user=owner, workspace_id=workspace.pk, status=status)


def test_resolves_user_group_workspace_organization_and_all_ranges_without_name_authority():
    operator = _operator()
    owner = User.objects.create_user("owner@test")
    organization = Organization.objects.create(name="Org")
    OrganizationMembership.objects.create(
        organization=organization,
        user=operator,
        role=OrganizationRole.ADMIN.value,
    )
    workspace = Workspace.objects.create(organization=organization, name="Workspace")
    WorkspaceMembership.objects.create(workspace=workspace, user=operator, role=WorkspaceRole.OWNER.value)
    ranges = tuple(_range(owner, workspace) for _ in range(3))

    group = Group.objects.create(name="name-is-display-only")
    group.user_set.add(owner)
    management_services.set_model_access_group_eligibility(
        operator,
        group.pk,
        managed_membership=True,
        spending_approved=False,
        expected_revision=0,
    )

    cases = (
        (SharingSelector(kind=SelectorKind.USER, ids=(str(owner.pk),)), 3, "management"),
        (SharingSelector(kind=SelectorKind.AUTH_GROUP, ids=(str(group.pk),)), 3, "management"),
        (SharingSelector(kind=SelectorKind.WORKSPACE, ids=(str(workspace.uuid),)), 3, "workspaces"),
        (SharingSelector(kind=SelectorKind.ORGANIZATION, ids=(str(organization.uuid),)), 3, "workspaces"),
        (SharingSelector(kind=SelectorKind.ALL_RANGES), 3, "engine"),
    )
    for selector, expected_count, authority_owner in cases:
        resolution = resolve_model_access_selector(operator, selector)
        assert len(resolution.member_refs) == expected_count
        assert resolution.selector_authority_refs[0].owner == authority_owner
        assert {item.reference for item in resolution.member_refs} == {
            f"range:{range_obj.uuid}" for range_obj in ranges
        }

    group_resolution = resolve_model_access_selector(
        operator,
        SharingSelector(kind=SelectorKind.AUTH_GROUP, ids=(str(group.pk),)),
    )
    assert group_resolution.spending_eligibilities[0].basis.value == "managed_membership"
    all_resolution = resolve_model_access_selector(
        operator,
        SharingSelector(kind=SelectorKind.ALL_RANGES),
    )
    assert all_resolution.publisher_requirements[0].scope is PublisherAuthorityScope.DEPLOYMENT


def test_user_selector_allows_self_service_but_denies_another_users_ranges():
    owner = User.objects.create_user("user-selector-owner@test")
    outsider = User.objects.create_user("user-selector-outsider@test")
    organization = Organization.objects.create(name="User Selector Org")
    workspace = Workspace.objects.create(organization=organization, name="User Selector Workspace")
    owned = _range(owner, workspace)
    outsiders = _range(outsider, workspace)

    with pytest.raises(ModelAccessCompositionError):
        resolve_model_access_selector(
            outsider,
            SharingSelector(kind=SelectorKind.USER, ids=(str(owner.pk),)),
        )

    resolution = resolve_model_access_selector(
        outsider,
        SharingSelector(kind=SelectorKind.USER, ids=(str(outsider.pk),)),
    )
    assert {item.reference for item in resolution.member_refs} == {f"range:{outsiders.uuid}"}
    assert f"range:{owned.uuid}" not in {item.reference for item in resolution.member_refs}


def test_all_ranges_selector_denies_non_operator_actor():
    actor = User.objects.create_user("all-ranges-outsider@test")

    with pytest.raises(ModelAccessCompositionError):
        resolve_model_access_selector(actor, SharingSelector(kind=SelectorKind.ALL_RANGES))


def test_selected_ranges_require_complete_owner_or_operator_authority_and_fail_closed():
    owner = User.objects.create_user("selected-owner@test")
    outsider = User.objects.create_user("selected-outsider@test")
    organization = Organization.objects.create(name="Selected Org")
    workspace = Workspace.objects.create(organization=organization, name="Selected Workspace")
    owned = _range(owner, workspace)
    foreign = _range(outsider, workspace)
    selector = SharingSelector(
        kind=SelectorKind.SELECTED_RANGES,
        ids=(str(owned.uuid), str(foreign.uuid)),
    )

    with pytest.raises(ModelAccessCompositionError):
        resolve_model_access_selector(owner, selector)

    single = resolve_model_access_selector(
        owner,
        SharingSelector(kind=SelectorKind.SELECTED_RANGES, ids=(str(owned.uuid),)),
    )
    assert single.member_refs[0].reference == f"range:{owned.uuid}"


def test_deleted_unknown_and_empty_selected_membership_fail_closed():
    operator = _operator()
    with pytest.raises(ModelAccessCompositionError):
        resolve_model_access_selector(
            operator,
            SharingSelector(
                kind=SelectorKind.SELECTED_RANGES,
                ids=("00000000-0000-4000-8000-000000000000",),
            ),
        )


def test_selected_ranges_can_mix_personal_and_ctf_authority_without_ctf_owner_fallback():
    organizer_user = User.objects.create_user("selected-organizer@test")
    ctf_user = User.objects.create_user("selected-ctf-user@example.com")
    organization = Organization.objects.create(name="Mixed Selected Org")
    workspace = Workspace.objects.create(organization=organization, name="Mixed Selected Workspace")
    ctf_event = CTFEvent.objects.create(
        name="Selected CTF Event",
        created_by=organizer_user,
        workspace_id=workspace.pk,
        status=EventStatus.REGISTRATION.value,
        event_start=timezone.now() + timedelta(days=1),
        event_end=timezone.now() + timedelta(days=2),
    )
    personal_range = _range(organizer_user, workspace)
    request_uuid = uuid4()
    cms_request = CmsRequest.objects.create(
        request_id=request_uuid,
        request_type=RequestType.RANGE.value,
        user=ctf_user,
        workspace_id=workspace.pk,
    )
    engine_request = EngineRequest.objects.create(
        request_id=request_uuid,
        request_type=RequestType.RANGE.value,
        user=ctf_user,
    )
    ctf_range = Range.objects.create(
        request=engine_request,
        user=ctf_user,
        workspace_id=workspace.pk,
        status=Range.Status.READY,
    )
    cms_range = RangeInstance.objects.create(
        request=cms_request,
        scenario_id="ctf",
        user_id=ctf_user.pk,
        workspace_id=workspace.pk,
        status=Range.Status.READY,
    )
    CTFParticipant.objects.create(
        event=ctf_event,
        user=ctf_user,
        name="CTF owner",
        email="selected-ctf-user@example.com",
        status=ParticipantStatus.REGISTERED.value,
        registered_at=timezone.now(),
        range_instance_id=cms_range.pk,
    )
    selector = SharingSelector(
        kind=SelectorKind.SELECTED_RANGES,
        ids=(str(personal_range.uuid), str(ctf_range.uuid)),
    )

    resolution = resolve_model_access_selector(organizer_user, selector)

    assert {item.reference for item in resolution.member_refs} == {
        f"range:{personal_range.uuid}",
        f"range:{ctf_range.uuid}",
    }
    assert {item.selector_digest for item in resolution.publisher_requirements} == {resolution.selector_digest}
    assert {item.authority_ref.owner for item in resolution.publisher_requirements} == {
        "ctf",
        "engine",
    }
    with pytest.raises(ModelAccessCompositionError):
        resolve_model_access_selector(
            ctf_user,
            SharingSelector(kind=SelectorKind.SELECTED_RANGES, ids=(str(ctf_range.uuid),)),
        )


def test_selected_range_correlation_maps_engine_uuid_to_active_cms_instance():
    owner = User.objects.create_user("correlation-owner@test")
    organization = Organization.objects.create(name="Correlation Org")
    workspace = Workspace.objects.create(organization=organization, name="Correlation Workspace")
    request_uuid = uuid4()
    cms_request = CmsRequest.objects.create(
        request_id=request_uuid,
        request_type=RequestType.RANGE.value,
        user=owner,
        workspace_id=workspace.pk,
    )
    engine_request = EngineRequest.objects.create(
        request_id=request_uuid,
        request_type=RequestType.RANGE.value,
        user=owner,
    )
    engine_range = Range.objects.create(
        request=engine_request,
        user=owner,
        workspace_id=workspace.pk,
        status=Range.Status.READY,
    )
    cms_range = RangeInstance.objects.create(
        request=cms_request,
        scenario_id="basic",
        user_id=owner.pk,
        workspace_id=workspace.pk,
        status=Range.Status.READY,
    )

    resolved = cms_services.resolve_model_access_selected_ranges((engine_range.uuid,))

    assert resolved[0].range_instance_id == cms_range.pk
    assert resolved[0].range_view.range_ref.reference == f"range:{engine_range.uuid}"
