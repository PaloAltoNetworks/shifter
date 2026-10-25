"""Launch selections are closed intent and survive replay and preparation."""

from uuid import uuid4

import pytest

from mission_control.api.serializers import LaunchRangeSerializer


def selection():
    return {
        "aliases": [
            {
                "logical_alias": "coding-main",
                "sources": [
                    {"source_id": str(uuid4()), "revision": 1, "weight": 2},
                    {"source_id": str(uuid4()), "revision": 3, "weight": 1},
                ],
            }
        ]
    }


def test_launch_serializer_preserves_weighted_choices_and_rejects_transport_injection():
    chosen = selection()
    serializer = LaunchRangeSerializer(data={"agents": {}, "scenario": "synthetic", "model_sources": chosen})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["model_sources"] == chosen
    chosen["url"] = "https://foreign.example.test"
    invalid = LaunchRangeSerializer(data={"agents": {}, "model_sources": chosen})
    assert not invalid.is_valid()


@pytest.mark.django_db
def test_retry_intent_cannot_reuse_a_key_for_different_source_choices(django_user_model):
    from cms.services._retry_safe_launch import _digest

    actor = django_user_model.objects.create_user(username="source-launcher")
    original = _digest(actor, "synthetic", {"agents": {}}, None, "synthetic", model_sources=selection())
    changed = _digest(actor, "synthetic", {"agents": {}}, None, "synthetic", model_sources=selection())
    assert original != changed
    assert _digest(actor, "synthetic", {"agents": {}}, None, "synthetic") == _digest(
        actor, "synthetic", {"agents": {}}, None, "synthetic", model_sources={"aliases": []}
    )


@pytest.mark.django_db(transaction=True)
def test_cms_preparation_pins_authorized_sources_and_spending_fences(django_user_model, settings, monkeypatch):
    from unittest.mock import Mock

    from cms.services._model_allocation import prepare_model_access_for_dispatch
    from engine.models import ModelLaunchPreparationRecord
    from engine.services import create_model_source
    from tests.cms.test_model_allocation_dispatch import setup_launch
    from tests.engine.services.test_model_sources import configuration, direct_source_catalog
    from workspaces.models import OrganizationMembership, Workspace

    actor, request, instance = setup_launch(django_user_model, settings)
    from cms.models import ScenarioModelNeeds

    authored = ScenarioModelNeeds.objects.get(scenario_id=instance.scenario_id)
    authored.needs["participant"]["data_regions"].append("provider-managed")
    authored.save()
    base = direct_source_catalog(request.deployment_id)
    settings.MODEL_ACCESS_CATALOG = base
    org = Workspace.objects.get(pk=instance.workspace_id).organization
    OrganizationMembership.objects.update_or_create(user=actor, organization=org, defaults={"role": "admin"})
    store = Mock()
    store.create_owned_secret.return_value = "projects/platform-example/secrets/synthetic/versions/1"
    monkeypatch.setattr("shared.cloud.get_secrets_store", lambda: store)
    source = create_model_source(
        actor,
        org.uuid,
        configuration(allow_organization_members=True, region="provider-managed"),
        credential={"api_key": "synthetic-secret"},
    )
    instance.model_sources = {
        "aliases": [
            {"logical_alias": "coding-main", "sources": [{"source_id": str(source.id), "revision": 1, "weight": 1}]}
        ]
    }
    instance.save(update_fields=["model_sources"])
    prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    prepared = ModelLaunchPreparationRecord.objects.get(request_id=request.request_id)
    assert prepared.catalog["contract_version"] == "model-access-policy/v4"
    assert any(item["source_id"] == str(source.id) for item in prepared.catalog["source_bindings"])
    assert any(
        item["authority_ref"]["reference"] == f"model-source:{source.id}"
        for item in prepared.intent["authority_revisions"]
    )
    assert "synthetic-secret" not in str(prepared.catalog)


def _allocated_source_launch(django_user_model, settings, monkeypatch, mixed=False):
    from unittest.mock import Mock

    from django.db import transaction

    from cms.services._model_allocation import prepare_model_access_for_dispatch
    from engine.services import create_model_source
    from engine.services._model_allocation_launch import allocate_launch_models
    from tests.cms.test_model_allocation_dispatch import setup_launch
    from tests.engine.services.test_model_sources import configuration, direct_source_catalog
    from workspaces.models import OrganizationMembership, Workspace

    actor, request, instance = setup_launch(django_user_model, settings)
    from cms.models import ScenarioModelNeeds

    authored = ScenarioModelNeeds.objects.get(scenario_id=instance.scenario_id)
    authored.needs["participant"]["data_regions"].append("provider-managed")
    authored.save()
    catalog = direct_source_catalog(request.deployment_id)
    if mixed:
        from shared.model_access import seal_catalog

        policy = catalog.model_dump(mode="json")
        policy["profiles"][0]["allowed_strategies"] = ["fixed-v1", "weighted-rendezvous-v1"]
        catalog = seal_catalog(policy)
    settings.MODEL_ACCESS_CATALOG = catalog
    org = Workspace.objects.get(pk=instance.workspace_id).organization
    OrganizationMembership.objects.update_or_create(user=actor, organization=org, defaults={"role": "admin"})
    store = Mock()
    store.create_owned_secret.return_value = "projects/platform-example/secrets/synthetic/versions/1"
    monkeypatch.setattr("shared.cloud.get_secrets_store", lambda: store)
    source = create_model_source(
        actor,
        org.uuid,
        configuration(region="provider-managed", allow_organization_members=True),
        credential={"api_key": "synthetic-secret"},
    )
    instance.model_sources = {
        "aliases": [
            {"logical_alias": "coding-main", "sources": [{"source_id": str(source.id), "revision": 1, "weight": 1}]}
        ]
    }
    if mixed:
        from cms.models import ScenarioModelNeeds
        from tests.cms.test_launch_model_admission import _need_payload

        need = _need_payload(digest=request.need.scenario_digest)
        need["allowed_strategies"] = ["fixed-v1", "weighted-rendezvous-v1"]
        need["data_regions"].append("provider-managed")
        authored = ScenarioModelNeeds.objects.get(scenario_id=instance.scenario_id)
        authored.needs = {"participant": need}
        authored.save()
        second = create_model_source(
            actor,
            org.uuid,
            configuration(region="provider-managed", name="Second source", allow_organization_members=True),
            credential={"api_key": "synthetic-second-secret"},
        )
        instance.model_sources["aliases"][0]["sources"].append(
            {"source_id": str(second.id), "revision": 1, "weight": 3}
        )
    instance.save(update_fields=["model_sources"])
    with transaction.atomic():
        prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
        (allocation,) = allocate_launch_models(
            {"resource": "raes-range", "operation": "provision", "request_id": str(request.request_id)},
            request.operation_id,
        )
    return actor, request, instance, source, allocation, org, catalog


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mixed", [False, True])
def test_source_application_cap_reaches_allocator_without_deployment_file_write(
    django_user_model, settings, monkeypatch, mixed
):
    _actor, _request, instance, _source, allocation, _org, catalog = _allocated_source_launch(
        django_user_model, settings, monkeypatch, mixed
    )
    choices = instance.model_sources["aliases"][0]["sources"]
    assert allocation.snapshot["shards"]["coding-main"]["credential_ref"]["reference"] in {
        f"source:{c['source_id']}:1" for c in choices
    }
    reading = allocation.draws.get().reservation.observation
    assert reading["source"] == "application_cap"
    assert settings.MODEL_ACCESS_CATALOG.digest == catalog.digest


@pytest.mark.django_db(transaction=True)
def test_member_cannot_edit_another_ranges_model_policy(django_user_model, settings):
    from cms.services import change_range_model_sources
    from tests.cms.test_model_allocation_dispatch import setup_launch
    from workspaces.services import WorkspaceAuthorizationError

    _, request, _ = setup_launch(django_user_model, settings)
    outsider = django_user_model.objects.create_user(username="source-foreign-editor", is_staff=True)
    with pytest.raises(WorkspaceAuthorizationError):
        change_range_model_sources(
            outsider, request_id=request.request_id, expected_revision=0, selection={"aliases": []}
        )


@pytest.mark.django_db(transaction=True)
def test_tenant_admin_can_inspect_range_model_sources_without_workspace_seat(django_user_model, settings):
    from cms.services import get_range_model_sources
    from tests.cms.test_model_allocation_dispatch import setup_launch
    from workspaces.models import OrganizationMembership, Workspace

    _, request, instance = setup_launch(django_user_model, settings)
    organization = Workspace.objects.get(pk=instance.workspace_id).organization
    admin = django_user_model.objects.create_user(username="tenant-model-admin", is_staff=False)
    OrganizationMembership.objects.create(user=admin, organization=organization, role="admin")
    result = get_range_model_sources(admin, request_id=request.request_id)
    assert result["request_id"] == request.request_id
    assert result["selection"] == {"aliases": []}


@pytest.mark.django_db(transaction=True)
def test_live_admin_policy_edit_preserves_generation_and_old_liability(django_user_model, settings, monkeypatch):
    from cms.services import change_range_model_sources
    from engine.models import ModelAllocation, Range
    from engine.services import create_model_source
    from shared.model_access import ContractError
    from tests.engine.services.test_model_sources import configuration

    actor, request, _instance, _source, old, org, _catalog = _allocated_source_launch(
        django_user_model, settings, monkeypatch
    )
    row = Range.objects.get(uuid=request.range_id)
    row.status = Range.Status.READY
    row.save(update_fields=["status"])
    old.unresolved_liabilities = 1
    old.save(update_fields=["unresolved_liabilities"])
    replacement = create_model_source(
        actor,
        org.uuid,
        configuration(region="provider-managed", quota_identity="account:second", allow_organization_members=True),
        credential={"api_key": "synthetic-replacement"},
    )
    selection = {
        "aliases": [{"logical_alias": "coding-main", "sources": [{"source_id": str(replacement.id), "revision": 1}]}]
    }
    result = change_range_model_sources(actor, request_id=request.request_id, expected_revision=0, selection=selection)
    assert result["error"] == ""
    assert result["revision"] == 1
    assert result["runtime"]["state"] == "refresh_pending"
    old.refresh_from_db()
    assert old.grant.state == "revoked" and old.unresolved_liabilities == 1
    successor = ModelAllocation.objects.get(request_id=request.request_id, source_policy_revision=1)
    assert successor.operation_id == old.operation_id
    with pytest.raises(ContractError, match=r"source\.revision_conflict"):
        change_range_model_sources(actor, request_id=request.request_id, expected_revision=0, selection=selection)


@pytest.mark.django_db(transaction=True)
def test_source_organization_membership_loss_revokes_live_allocation(django_user_model, settings, monkeypatch):
    from workspaces.models import OrganizationMembership

    actor, _request, _instance, _source, allocation, org, _catalog = _allocated_source_launch(
        django_user_model, settings, monkeypatch
    )
    OrganizationMembership.objects.filter(user=actor, organization=org).delete()
    allocation.grant.refresh_from_db()
    assert allocation.grant.state == "revoked"


@pytest.mark.django_db(transaction=True)
def test_pending_range_edit_retries_same_policy_after_interrupted_admission(django_user_model, settings, monkeypatch):
    from cms.models import RangeInstance
    from cms.services import _model_allocation, change_range_model_sources
    from engine.models import Range

    actor, request, instance, _source, allocation, _org, _catalog = _allocated_source_launch(
        django_user_model, settings, monkeypatch
    )
    Range.objects.filter(uuid=request.range_id).update(status=Range.Status.READY)
    prepare = _model_allocation.prepare_model_access_for_dispatch

    def interrupted(*args, **kwargs):
        raise RuntimeError("synthetic interruption between commits")

    monkeypatch.setattr(_model_allocation, "prepare_model_access_for_dispatch", interrupted)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        change_range_model_sources(
            actor, request_id=request.request_id, expected_revision=0, selection=instance.model_sources
        )
    current = RangeInstance.objects.get(pk=instance.pk)
    assert current.model_source_policy_revision == 1 and current.model_source_policy_error == "source.admission_pending"
    allocation.grant.refresh_from_db()
    assert allocation.grant.state == "revoked"
    monkeypatch.setattr(_model_allocation, "prepare_model_access_for_dispatch", prepare)
    result = change_range_model_sources(
        actor, request_id=request.request_id, expected_revision=1, selection=instance.model_sources
    )
    assert result["revision"] == 1 and result["error"] == ""
    assert result["runtime"]["state"] == "refresh_pending"


@pytest.mark.django_db(transaction=True)
def test_rotated_credential_with_unresolved_usage_is_retained(django_user_model, settings, monkeypatch):
    from datetime import timedelta

    from django.utils import timezone

    import shared.cloud
    from engine.models import ModelSourceRevision
    from engine.services import retire_unused_model_source_credentials, update_model_source
    from tests.engine.services.test_model_sources import configuration

    actor, _request, _instance, source, allocation, org, _catalog = _allocated_source_launch(
        django_user_model, settings, monkeypatch
    )
    allocation.unresolved_liabilities = 1
    allocation.save(update_fields=["unresolved_liabilities"])
    ModelSourceRevision.objects.filter(source_id=source.id).update(created_at=timezone.now() - timedelta(minutes=20))
    update_model_source(
        actor,
        org.uuid,
        source.id,
        expected_revision=1,
        configuration=configuration(allow_organization_members=True),
        credential={"api_key": "synthetic-new"},
    )
    assert retire_unused_model_source_credentials(actor, org.uuid, source.id) == 0
    shared.cloud.get_secrets_store().retire_owned_secret.assert_not_called()
    assert ModelSourceRevision.objects.get(source_id=source.id, revision=1).retired_at is None


@pytest.mark.parametrize("value", [True, "1", 1.0])
def test_model_policy_write_revisions_do_not_coerce_json_scalars(value):
    from cms.api.model_sources import ModelSourceUpdateSerializer
    from cms.api.range_model_sources import RangeModelSourcesWriteSerializer
    from ctf.api.serializers.organizer import EventWriteSerializer
    from tests.engine.services.test_model_sources import configuration

    writes = [
        ModelSourceUpdateSerializer(data={"configuration": configuration(), "expected_revision": value}),
        RangeModelSourcesWriteSerializer(data={"selection": {"aliases": []}, "expected_revision": value}),
        EventWriteSerializer(data={"expected_model_source_revision": value}, partial=True),
    ]
    for serializer in writes:
        assert not serializer.is_valid()
        assert any("revision" in key for key in serializer.errors)
