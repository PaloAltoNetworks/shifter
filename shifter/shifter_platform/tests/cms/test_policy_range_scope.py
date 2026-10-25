"""Prepared scope moves prove both scopes and reconcile every persisted projection."""

import pytest
from django.db import transaction

from cms import services
from cms.exceptions import RangeScopeAdminError
from management import services as identities
from tests.cms.test_policy_offboarding import owned_resources as _owned_resources
from tests.workspaces.test_account_policy_admin import Provider
from workspaces import services as workspaces
from workspaces.models import Organization, Workspace, WorkspaceQuotaReservation

owned_resources = _owned_resources

pytestmark = pytest.mark.django_db


def test_service_moves_scope_and_quota_reservation_together_and_can_move_back(owned_resources):
    actor, source, _, source_workspace, cms_request, engine_range, _, instance = owned_resources
    account = workspaces.create_account(kind="team", name="Destination")
    organization = Organization.objects.get(account_id=account.id)
    destination = Workspace.objects.get(organization=organization)
    workspaces.admin_add_scope_member(
        actor, Provider(), "workspace", destination.uuid, identities.principal_for_user(source)
    )
    audit = workspaces.WorkspaceQuotaAuditContext(
        actor_type="principal", actor_id=None, actor_principal_uuid=actor.principal.uuid
    )
    with transaction.atomic():
        workspaces.reserve_workspace_concurrent_range(source_workspace.pk, cms_request.request_id, audit)
    services.policy_rebind_range_workspace(
        actor, Provider(), request_id=cms_request.request_id, target_workspace_uuid=destination.uuid
    )
    for row in (cms_request, engine_range, instance):
        row.refresh_from_db()
        assert (row.account_id, row.organization_id, row.workspace_id) == (account.id, organization.pk, destination.pk)
    assert WorkspaceQuotaReservation.objects.filter(workspace=destination, released_at__isnull=True).count() == 1
    services.policy_rebind_range_workspace(
        actor, Provider(), request_id=cms_request.request_id, target_workspace_uuid=source_workspace.uuid
    )
    assert WorkspaceQuotaReservation.objects.filter(workspace=source_workspace, released_at__isnull=True).count() == 1
    assert WorkspaceQuotaReservation.objects.filter(workspace=destination, released_at__isnull=True).count() == 0


def test_missing_destination_authority_or_capacity_preserves_all_projections(owned_resources):
    actor, source, _, workspace, cms_request, engine_range, _, instance = owned_resources
    account = workspaces.create_account(kind="team", name="Destination")
    destination = Workspace.objects.get(organization__account_id=account.id)
    workspaces.admin_add_scope_member(
        actor, Provider(), "workspace", destination.uuid, identities.principal_for_user(source)
    )
    audit = workspaces.WorkspaceQuotaAuditContext(actor_type="principal", actor_id=None)
    with transaction.atomic():
        workspaces.reserve_workspace_concurrent_range(workspace.pk, cms_request.request_id, audit)
    for provider in (Provider(allowed_targets=frozenset({workspace.uuid})),):
        with pytest.raises(RangeScopeAdminError):
            services.policy_rebind_range_workspace(
                actor, provider, request_id=cms_request.request_id, target_workspace_uuid=destination.uuid
            )
    workspaces.admin_set_workspace_quota_policy(
        actor, Provider(), destination.uuid, "concurrent_ranges", 0, "enforcing"
    )
    with pytest.raises(RangeScopeAdminError):
        services.policy_rebind_range_workspace(
            actor, Provider(), request_id=cms_request.request_id, target_workspace_uuid=destination.uuid
        )
    for row in (cms_request, engine_range, instance):
        row.refresh_from_db()
        assert row.workspace_id == workspace.pk


def test_policy_range_list_and_prepared_http_rebind(owned_resources, monkeypatch):
    from django.test import override_settings
    from rest_framework.test import APIClient

    from cms.api.policy_range_scope import PolicyRangeWorkspaceRebindView

    actor, source, _, workspace, request, _, _, _ = owned_resources
    assert PolicyRangeWorkspaceRebindView is not None
    rows = services.policy_list_range_scope_bindings(actor, Provider(), workspace_uuid=workspace.uuid)
    assert [row.request.request_id for row in rows] == [request.request_id]
    with pytest.raises(RangeScopeAdminError):
        services.policy_list_range_scope_bindings(
            actor, Provider(allowed_targets=frozenset()), workspace_uuid=workspace.uuid
        )
    client = APIClient()

    def authenticate(_self, incoming):
        incoming.credential_context = actor
        return None, actor

    monkeypatch.setattr("shared.api_tokens.authentication.ApiTokenAuthentication.authenticate", authenticate)
    monkeypatch.setattr("shared.authorization.port._provider_factory", Provider)
    client.credentials(HTTP_AUTHORIZATION="Bearer admitted-service")
    audit = workspaces.WorkspaceQuotaAuditContext(
        actor_type="principal", actor_id=None, actor_principal_uuid=actor.principal.uuid
    )
    with transaction.atomic():
        workspaces.reserve_workspace_concurrent_range(workspace.pk, request.request_id, audit)
    with override_settings(ROOT_URLCONF="config.account_admin_urls"):
        response = client.get(f"/api/v1/cms/workspaces/{workspace.uuid}/range-scoping/")
        assert response.status_code == 200 and response.data["count"] == 1
        response = client.post(
            f"/api/v1/cms/ranges/{request.request_id}/workspace/",
            {"target_workspace_uuid": str(workspace.uuid)},
            format="json",
        )
        assert response.status_code == 200 and response.data["changed"] is False
        assert (
            client.post(
                f"/api/v1/cms/ranges/{request.request_id}/workspace/",
                {"target_workspace_uuid": str(workspace.uuid), "owner_id": source.pk},
                format="json",
            ).status_code
            == 400
        )


def test_archived_source_discovery_and_strict_audit_rollback(owned_resources, monkeypatch):
    from django.utils import timezone

    actor, source, _, workspace, request, engine_range, _, instance = owned_resources
    workspace.archived_at = timezone.now()
    workspace.save(update_fields=["archived_at"])
    assert services.policy_list_range_scope_bindings(actor, Provider(), workspace_uuid=workspace.uuid).count() == 1
    account = workspaces.create_account(kind="team", name="Destination")
    destination = Workspace.objects.get(organization__account_id=account.id)
    workspaces.admin_add_scope_member(
        actor, Provider(), "workspace", destination.uuid, identities.principal_for_user(source)
    )
    audit = workspaces.WorkspaceQuotaAuditContext(
        actor_type="principal", actor_id=None, actor_principal_uuid=actor.principal.uuid
    )
    with transaction.atomic():
        workspaces.reserve_workspace_concurrent_range(workspace.pk, request.request_id, audit)

    def failed_audit(*_args, **_kwargs):
        raise RuntimeError("Synthetic audit storage failure")

    monkeypatch.setattr("cms.services._policy_range_scope.audit_log", failed_audit)
    with pytest.raises(RuntimeError):
        services.policy_rebind_range_workspace(
            actor, Provider(), request_id=request.request_id, target_workspace_uuid=destination.uuid
        )
    for row in (request, engine_range, instance):
        row.refresh_from_db()
        assert row.workspace_id == workspace.pk
    assert not WorkspaceQuotaReservation.objects.filter(workspace=destination).exists()


def test_terminal_event_with_pre_move_projection_releases_destination_quota(owned_resources, monkeypatch):
    from cms.handlers.range_events import apply_range_status
    from shared.enums import ResourceStatus

    actor, source, _, workspace, request, _, _, instance = owned_resources
    stale = type(instance).objects.get(pk=instance.pk)
    account = workspaces.create_account(kind="team", name="Destination")
    destination = Workspace.objects.get(organization__account_id=account.id)
    workspaces.admin_add_scope_member(
        actor, Provider(), "workspace", destination.uuid, identities.principal_for_user(source)
    )
    audit = workspaces.WorkspaceQuotaAuditContext(
        actor_type="principal", actor_id=None, actor_principal_uuid=actor.principal.uuid
    )
    with transaction.atomic():
        workspaces.reserve_workspace_concurrent_range(workspace.pk, request.request_id, audit)
    services.policy_rebind_range_workspace(
        actor, Provider(), request_id=request.request_id, target_workspace_uuid=destination.uuid
    )
    monkeypatch.setattr("cms.handlers.range_events.notify_ctf_range_status", lambda *_args, **_kwargs: None)
    assert apply_range_status(stale, ResourceStatus.DESTROYED.value)
    assert not WorkspaceQuotaReservation.objects.filter(
        correlation_key=str(request.request_id), released_at__isnull=True
    ).exists()


def test_terminal_convergence_before_scope_move_does_not_reopen_capacity(owned_resources, monkeypatch):
    from cms.handlers.range_events import apply_range_status
    from shared.enums import ResourceStatus

    actor, source, _, workspace, request, _, _, instance = owned_resources
    account = workspaces.create_account(kind="team", name="Destination")
    destination = Workspace.objects.get(organization__account_id=account.id)
    workspaces.admin_add_scope_member(
        actor, Provider(), "workspace", destination.uuid, identities.principal_for_user(source)
    )
    audit = workspaces.WorkspaceQuotaAuditContext(
        actor_type="principal", actor_id=None, actor_principal_uuid=actor.principal.uuid
    )
    with transaction.atomic():
        workspaces.reserve_workspace_concurrent_range(workspace.pk, request.request_id, audit)
    monkeypatch.setattr("cms.handlers.range_events.notify_ctf_range_status", lambda *_args, **_kwargs: None)
    apply_range_status(instance, ResourceStatus.DESTROYED.value)
    with pytest.raises(RangeScopeAdminError):
        services.policy_rebind_range_workspace(
            actor, Provider(), request_id=request.request_id, target_workspace_uuid=destination.uuid
        )
    instance.refresh_from_db()
    assert instance.workspace_id == workspace.pk
    assert not WorkspaceQuotaReservation.objects.filter(
        correlation_key=str(request.request_id), released_at__isnull=True
    ).exists()
