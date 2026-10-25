"""Policy offboarding preserves source/destination eligibility and all owner projections."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from cms import services
from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from engine.models import Range as EngineRange
from engine.models import Request as EngineRequest
from management import services as identities
from shared.authorization import APPLICATION_ADMINISTRATOR_ACTIONS
from shared.enums import RangeSource, RequestType, ResourceStatus
from shared.models import AuditLog
from tests.workspaces.test_account_policy_admin import Provider, _actor
from workspaces import services as workspaces
from workspaces.models import Organization, Workspace, WorkspaceOwnership

pytestmark = pytest.mark.django_db


@pytest.fixture
def owned_resources():
    source = get_user_model().objects.create_user(username=f"source-{uuid4()}")
    destination = get_user_model().objects.create_user(username=f"destination-{uuid4()}")
    source_ref, destination_ref = identities.principal_for_user(source), identities.principal_for_user(destination)
    account = workspaces.create_account(kind="team", name="Customer")
    organization = Organization.objects.get(account_id=account.id)
    workspace = Workspace.objects.get(organization=organization)
    actor = _actor("service", actions=APPLICATION_ADMINISTRATOR_ACTIONS | frozenset({"range.manage"}))
    for principal in (source_ref, destination_ref):
        workspaces.admin_add_scope_member(actor, Provider(), "workspace", workspace.uuid, principal)
    WorkspaceOwnership.objects.create(workspace=workspace, principal_uuid=source_ref.uuid)
    request_id = uuid4()
    scope = {
        "scope_kind": "account",
        "account_id": account.id,
        "organization_id": organization.pk,
        "workspace_id": workspace.pk,
    }
    cms_request = CmsRequest.objects.create(
        request_id=request_id, request_type=RequestType.RANGE.value, user=source, **scope
    )
    engine_request = EngineRequest.objects.create(
        request_id=request_id, request_type=RequestType.RANGE.value, user=source
    )
    engine_range = EngineRange.objects.create(
        user=source,
        cms_user_id=source.pk,
        request=engine_request,
        status=EngineRange.Status.READY,
        subnet_index=EngineRange.allocate_subnet_index(),
        **scope,
    )
    instance = RangeInstance.objects.create(
        request=cms_request,
        user_id=source.pk,
        scenario_id="synthetic",
        range_source=RangeSource.MISSION_CONTROL.value,
        status=ResourceStatus.READY.value,
        **scope,
    )
    return actor, source, destination, workspace, cms_request, engine_range, engine_request, instance


def test_service_offboards_inactive_source_without_membership_or_policy_side_effects(owned_resources):
    actor, source, destination, workspace, cms_request, engine_range, engine_request, instance = owned_resources
    source.is_active = False
    source.save(update_fields=["is_active"])
    summary = services.policy_transfer_user_ownership(
        actor, Provider(), source, destination, kinds=("workspaces", "ranges")
    )
    assert summary.workspaces_transferred == 1 and summary.ranges_reassigned == 1
    for row in (workspace, cms_request, engine_range, engine_request, instance):
        row.refresh_from_db()
    assert workspace.ownerships.get().principal_uuid == identities.principal_for_user(destination).uuid
    assert cms_request.user_id == engine_range.user_id == engine_request.user_id == instance.user_id == destination.pk
    assert AuditLog.objects.filter(
        entity_type="range", actor_principal_uuid=actor.principal.uuid, action="update"
    ).exists()
    assert workspaces.admin_list_scope_members(actor, Provider(), "workspace", workspace.uuid).count == 2


def test_transfer_denial_and_projection_drift_preserve_ownership(owned_resources):
    actor, source, destination, _workspace, cms_request, engine_range, _engine_request, instance = owned_resources
    with pytest.raises(PermissionError):
        services.policy_transfer_user_ownership(actor, Provider(allowed=False), source, destination, kinds=("ranges",))
    engine_range.user = destination
    engine_range.save(update_fields=["user"])
    summary = services.policy_transfer_user_ownership(actor, Provider(), source, destination, kinds=("ranges",))
    assert summary.ranges_blocked == 1 and summary.ranges_reassigned == 0
    cms_request.refresh_from_db()
    instance.refresh_from_db()
    assert cms_request.user_id == instance.user_id == source.pk


def test_offboarding_does_not_fabricate_destination_membership(owned_resources):
    actor, source, destination, workspace, *_ = owned_resources
    principal = identities.principal_for_user(destination)
    workspaces.admin_remove_scope_member(actor, Provider(), "workspace", workspace.uuid, principal.uuid)
    summary = services.policy_transfer_user_ownership(
        actor, Provider(), source, destination, kinds=("workspaces", "ranges")
    )
    assert summary.workspaces_blocked_no_membership == 1 and summary.ranges_blocked == 1
    workspace.refresh_from_db()
    assert workspace.ownerships.get().principal_uuid == identities.principal_for_user(source).uuid


@pytest.mark.parametrize("policy", [True, False])
def test_offboarding_does_not_adopt_an_intervening_owner(owned_resources, monkeypatch, policy):
    from cms.services import _policy_offboarding, _user_offboarding
    from workspaces.models import WorkspaceMembership

    actor, source, destination, workspace, cms_request, engine_range, engine_request, instance = owned_resources
    intervening = get_user_model().objects.create_user(username=f"intervening-{uuid4()}")
    if not policy:
        WorkspaceMembership.objects.create(workspace=workspace, user=destination, role="member")
    module = _policy_offboarding if policy else _user_offboarding
    name = "policy_reassign_range_owner" if policy else "reassign_range_owner"
    original = getattr(module, name)

    def change_owner():
        for row in (instance, cms_request, engine_request):
            row.user_id = intervening.pk
            row.save(update_fields=["user_id"])
        engine_range.user_id = engine_range.cms_user_id = intervening.pk
        engine_range.save(update_fields=["user_id", "cms_user_id"])

    if policy:

        def race(*args, **kwargs):
            change_owner()
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, race)
    else:
        from types import SimpleNamespace

        original_filter = RangeInstance.objects.filter

        def enumerate_then_race(*args, **kwargs):
            rows = original_filter(*args, **kwargs)
            if kwargs.get("user_id") != source.pk:
                return rows
            ids = list(rows.values_list("pk", flat=True))
            change_owner()
            return SimpleNamespace(values_list=lambda *_args, **_kwargs: ids)

        monkeypatch.setattr(RangeInstance.objects, "filter", enumerate_then_race)
    if policy:
        result = services.policy_transfer_user_ownership(actor, Provider(), source, destination, kinds=("ranges",))
        assert result.ranges_blocked == 1 and result.ranges_reassigned == 0
    else:
        assert module._transfer_ranges(source, destination, module.OffboardingAuditContext("user", source.pk)) == (0, 1)
    for row in (instance, cms_request, engine_range, engine_request):
        row.refresh_from_db()
        assert row.user_id == intervening.pk


def test_active_range_collision_preserves_prior_workspace_transfer(owned_resources):
    actor, source, destination, workspace, *_rest, instance = owned_resources
    RangeInstance.objects.create(
        user_id=destination.pk,
        range_source=instance.range_source,
        status=instance.status,
        scenario_id="synthetic-destination",
        scope_kind=instance.scope_kind,
        account_id=instance.account_id,
        organization_id=instance.organization_id,
        workspace_id=instance.workspace_id,
    )
    result = services.policy_transfer_user_ownership(
        actor, Provider(), source, destination, kinds=("workspaces", "ranges")
    )
    assert result.workspaces_transferred == 1 and result.ranges_blocked == 1 and result.ranges_reassigned == 0
    instance.refresh_from_db()
    assert instance.user_id == source.pk
    assert workspace.ownerships.get().principal_uuid == identities.principal_for_user(destination).uuid


@pytest.mark.parametrize("drift", ["membership", "ownership"])
def test_later_workspace_rejection_retains_committed_offboarding_results(owned_resources, monkeypatch, drift):
    from cms.services import _policy_offboarding
    from workspaces.models import WorkspaceMembership

    actor, source, destination, workspace, *_ = owned_resources
    later = Workspace.objects.create(organization=workspace.organization, name="Later workspace")
    source_ref = identities.principal_for_user(source)
    destination_ref = identities.principal_for_user(destination)
    for principal in (source_ref, destination_ref):
        workspaces.admin_add_scope_member(actor, Provider(), "workspace", later.uuid, principal)
    WorkspaceOwnership.objects.create(workspace=later, principal_uuid=source_ref.uuid)
    original = _policy_offboarding.admin_transfer_workspace_principal

    def transfer(*args, **kwargs):
        if args[2] == later.uuid:
            if drift == "membership":
                WorkspaceMembership.objects.filter(workspace=later, principal_uuid=destination_ref.uuid).delete()
            else:
                WorkspaceOwnership.objects.filter(workspace=later, principal_uuid=source_ref.uuid).delete()
        return original(*args, **kwargs)

    monkeypatch.setattr(_policy_offboarding, "admin_transfer_workspace_principal", transfer)
    result = services.policy_transfer_user_ownership(actor, Provider(), source, destination, kinds=("workspaces",))
    assert result.workspaces_transferred == 1 and result.workspaces_blocked == 1
    assert result.workspaces_blocked_no_membership == 0
    assert workspace.ownerships.get().principal_uuid == destination_ref.uuid
    assert not later.ownerships.filter(principal_uuid=destination_ref.uuid).exists()


def _later_range(owned_resources, *, workspace=None):
    _, source, _, original_workspace, *_ = owned_resources
    workspace = workspace or original_workspace
    request_id = uuid4()
    scope = {
        "scope_kind": "account",
        "account_id": workspace.organization.account_id,
        "organization_id": workspace.organization_id,
        "workspace_id": workspace.pk,
    }
    intent = CmsRequest.objects.create(
        request_id=request_id, request_type=RequestType.RANGE.value, user=source, **scope
    )
    engine_intent = EngineRequest.objects.create(
        request_id=request_id, request_type=RequestType.RANGE.value, user=source
    )
    runtime = EngineRange.objects.create(
        user=source,
        cms_user_id=source.pk,
        request=engine_intent,
        status=EngineRange.Status.READY,
        subnet_index=EngineRange.allocate_subnet_index(),
        **scope,
    )
    other_source = next(item.value for item in RangeSource if item.value != RangeSource.MISSION_CONTROL.value)
    instance = RangeInstance.objects.create(
        request=intent,
        user_id=source.pk,
        scenario_id="synthetic-later",
        range_source=other_source,
        status=ResourceStatus.READY.value,
        **scope,
    )
    return instance, runtime


def _later_owned_workspace(owned_resources):
    actor, source, destination, workspace, *_ = owned_resources
    later = Workspace.objects.create(organization=workspace.organization, name="Later owned workspace")
    for user in (source, destination):
        workspaces.admin_add_scope_member(
            actor, Provider(), "workspace", later.uuid, identities.principal_for_user(user)
        )
    WorkspaceOwnership.objects.create(workspace=later, principal_uuid=identities.principal_for_user(source).uuid)
    return later


@pytest.mark.parametrize("archive_when", ["before_transfer", "before_lock"])
def test_archived_range_tenancy_retains_prior_committed_offboarding_counts(owned_resources, monkeypatch, archive_when):
    from cms.services import _policy_offboarding

    actor, source, destination, _, _, _, _, first = owned_resources
    archived = _later_owned_workspace(owned_resources)
    later, _ = _later_range(owned_resources, workspace=archived)

    def archive():
        archived.archived_at = timezone.now()
        archived.save(update_fields=["archived_at"])

    if archive_when == "before_transfer":
        archive()
    else:
        original = _policy_offboarding._transfer_locked

        def transfer(*args, **kwargs):
            if args[1].uuid == later.uuid:
                archive()
            return original(*args, **kwargs)

        monkeypatch.setattr(_policy_offboarding, "_transfer_locked", transfer)
    result = services.policy_transfer_user_ownership(actor, Provider(), source, destination, kinds=("ranges",))
    assert result.ranges_reassigned == 1 and result.ranges_blocked == 1
    first.refresh_from_db()
    later.refresh_from_db()
    assert first.user_id == destination.pk and later.user_id == source.pk


@pytest.mark.parametrize("missing_membership", [False, True])
def test_archived_workspace_is_blocked_without_aborting_eligible_offboarding(owned_resources, missing_membership):
    actor, source, destination, workspace, _, _, _, instance = owned_resources
    archived = _later_owned_workspace(owned_resources)
    source_ref = identities.principal_for_user(source)
    destination_ref = identities.principal_for_user(destination)
    if missing_membership:
        workspaces.admin_remove_scope_member(actor, Provider(), "workspace", archived.uuid, destination_ref.uuid)
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    provider = Provider()
    result = services.policy_transfer_user_ownership(
        actor, provider, source, destination, kinds=("workspaces", "ranges")
    )
    assert result.workspaces_transferred == 1 and result.workspaces_blocked == 1
    assert result.workspaces_blocked_no_membership == 0
    assert result.ranges_reassigned == 1 and result.ranges_blocked == 0
    assert workspace.ownerships.get().principal_uuid == destination_ref.uuid
    assert archived.ownerships.get().principal_uuid == source_ref.uuid
    instance.refresh_from_db()
    assert instance.user_id == destination.pk
    check = next(request for request in provider.requests if request.target.uuid == archived.uuid)
    assert check.action == "workspace.transfer"
    assert check.scope.workspace_uuid == archived.uuid
    assert check.scope.organization_uuid == archived.organization.uuid
    assert check.scope.account_uuid == archived.organization.account.uuid


def test_archived_workspace_still_requires_exact_policy_before_any_offboarding_effect(owned_resources):
    actor, source, destination, workspace, _, _, _, instance = owned_resources
    archived = _later_owned_workspace(owned_resources)
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    provider = Provider(allowed_targets=frozenset({None, workspace.uuid}))
    with pytest.raises(workspaces.AccountScopeError):
        services.policy_transfer_user_ownership(actor, provider, source, destination, kinds=("workspaces", "ranges"))
    assert provider.requests[-1].target.uuid == archived.uuid
    assert provider.requests[-1].action == "workspace.transfer"
    assert workspace.ownerships.get().principal_uuid == identities.principal_for_user(source).uuid
    instance.refresh_from_db()
    assert instance.user_id == source.pk


@pytest.mark.parametrize("rejection", ["policy", "projection"])
def test_later_range_rejection_retains_committed_offboarding_results(owned_resources, monkeypatch, rejection):
    from cms.services import _policy_offboarding
    from engine.services import RangeProjectionIntegrityError

    actor, source, destination, _, _, _, _, first = owned_resources
    later, _ = _later_range(owned_resources)
    original = _policy_offboarding.policy_reassign_range_owner

    def transfer(*args, **kwargs):
        if args[2] == later.uuid:
            error = PermissionError if rejection == "policy" else RangeProjectionIntegrityError
            raise error("Resource changed")
        return original(*args, **kwargs)

    monkeypatch.setattr(_policy_offboarding, "policy_reassign_range_owner", transfer)
    result = services.policy_transfer_user_ownership(actor, Provider(), source, destination, kinds=("ranges",))
    assert result.ranges_reassigned == 1 and result.ranges_blocked == 1
    first.refresh_from_db()
    later.refresh_from_db()
    assert first.user_id == destination.pk and later.user_id == source.pk


def test_legacy_offboarding_retains_prior_success_after_engine_projection_drift(owned_resources):
    from cms.services import _user_offboarding
    from workspaces.models import WorkspaceMembership

    _, source, destination, workspace, _, _, _, first = owned_resources
    WorkspaceMembership.objects.create(workspace=workspace, user=destination, role="member")
    later, runtime = _later_range(owned_resources)
    runtime.cms_user_id = destination.pk
    runtime.save(update_fields=["cms_user_id"])
    result = _user_offboarding._transfer_ranges(
        source, destination, _user_offboarding.OffboardingAuditContext("user", source.pk)
    )
    assert result == (1, 1)
    first.refresh_from_db()
    later.refresh_from_db()
    assert first.user_id == destination.pk and later.user_id == source.pk
