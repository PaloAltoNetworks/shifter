"""CMS supplies actual scenario/owner demand before the Engine launch commits."""

import pytest

from cms.models import RangeInstance, Request
from engine.models import ModelLaunchPreparationRecord
from shared.model_access import ContractError

from ..engine.services.test_model_allocation import allocation_inputs
from .test_launch_model_admission import _author, _need_payload, _register

pytestmark = pytest.mark.django_db(transaction=True)


def setup_launch(django_user_model, settings, *, owner=None, required=True):
    from engine.models import Range

    catalog, request, _ = allocation_inputs(django_user_model, user=owner)
    engine_range = Range.objects.get(uuid=request.range_id)
    actor = engine_range.user
    from workspaces.services import resolve_personal_workspace

    workspace_id = resolve_personal_workspace(actor).workspace_id
    engine_range.workspace_id = workspace_id
    engine_range.save(update_fields=["workspace_id"])
    _register(actor)
    _author(actor, needs={"participant": _need_payload(digest=request.need.scenario_digest, required=required)})
    cms_request = Request.objects.create(request_id=request.request_id, user=actor, workspace_id=workspace_id)
    instance = RangeInstance.objects.create(
        request=cms_request,
        scenario_id="scn",
        user_id=actor.pk,
        workspace_id=workspace_id,
        range_source="mission_control",
        model_package_digest=request.need.scenario_digest,
        expires_at=request.window_end,
        maximum_expires_at=request.window_end,
    )
    settings.MODEL_ACCESS_ENABLED = True
    settings.MODEL_ACCESS_CATALOG = catalog
    return actor, request, instance


def test_replaced_package_cannot_authorize_the_launched_snapshot(django_user_model, settings):
    from cms.services._model_allocation import prepare_model_access_for_dispatch

    _, request, instance = setup_launch(django_user_model, settings)
    instance.model_package_digest = "sha256:" + "f" * 64
    instance.save(update_fields=["model_package_digest"])
    with pytest.raises(ContractError, match=r"allocation\.scenario_unavailable"):
        prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    assert not ModelLaunchPreparationRecord.objects.exists()


def test_cms_prepares_the_real_owner_scenario_and_non_event_scope(django_user_model, settings):
    from cms.services._model_allocation import prepare_model_access_for_dispatch

    actor, request, _ = setup_launch(django_user_model, settings)
    prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    prepared = ModelLaunchPreparationRecord.objects.get(request_id=request.request_id)
    assert prepared.intent["owner_ref"] == {"owner": "management", "reference": f"user:{actor.pk}"}
    assert prepared.intent["scope"]["kind"] == "standalone"
    assert prepared.intent["needs"][0]["scenario_digest"] == request.need.scenario_digest


def test_normal_ready_transition_preserves_launch_grant(django_user_model, settings):
    from cms.services._model_allocation import prepare_model_access_for_dispatch
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ModelPendingGrant, Range
    from engine.services import record_model_observations

    _, request, _ = setup_launch(django_user_model, settings)
    _, _, observations = allocation_inputs(django_user_model)
    record_model_observations(settings.MODEL_ACCESS_CATALOG, lambda _: observations)
    prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    enqueue_provisioner_launch(["raes-range", "provision", "--request-id", str(request.request_id)])
    range_obj = Range.objects.get(uuid=request.range_id)
    range_obj.status = Range.Status.READY
    range_obj.save(update_fields=["status"])
    assert ModelPendingGrant.objects.get().state == "pending"


def test_sibling_ready_transition_does_not_revoke_shared_owner_grant(django_user_model):
    from engine.models import ModelPendingGrant, Range

    from ..engine.services.test_model_allocation import allocate

    owner = django_user_model.objects.create_user(username="model-sibling-owner")
    first = allocation_inputs(django_user_model, user=owner)
    first_allocation = allocate(first)
    second = allocation_inputs(django_user_model, user=owner)
    second_allocation = allocate(second)
    range_obj = Range.objects.get(uuid=first[1].range_id)
    range_obj.status = Range.Status.READY
    range_obj.save(update_fields=["status"])
    assert ModelPendingGrant.objects.get(allocation=first_allocation).state == "pending"
    assert ModelPendingGrant.objects.get(allocation=second_allocation).state == "pending"


def test_range_owner_change_revokes_its_launch_grant(django_user_model, settings):
    from cms.services._model_allocation import prepare_model_access_for_dispatch
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ModelPendingGrant, Range
    from engine.services import record_model_observations

    _, request, _ = setup_launch(django_user_model, settings)
    _, _, observations = allocation_inputs(django_user_model)
    record_model_observations(settings.MODEL_ACCESS_CATALOG, lambda _: observations)
    prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    enqueue_provisioner_launch(["raes-range", "provision", "--request-id", str(request.request_id)])
    range_obj = Range.objects.get(uuid=request.range_id)
    range_obj.user = django_user_model.objects.create_user(username="replacement-range-owner")
    range_obj.save(update_fields=["user"])

    assert ModelPendingGrant.objects.get().state == "revoked"


@pytest.mark.parametrize("exhausted", [False, True])
@pytest.mark.parametrize("overlay_removed", [False, True])
def test_warm_claim_model_decision_and_owner_transfer_are_atomic(
    django_user_model, settings, exhausted, overlay_removed
):
    from uuid import uuid4

    from django.db import transaction

    from cms.services._model_allocation import prepare_model_access_for_dispatch
    from cms.services._warm_pool_claim import WarmClaimRequest, _run_atomic_claim
    from cms.services._warm_pool_reconcile import create_managed_warm_user
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ModelAllocation, ProvisionerLaunchIntent, Range, WarmRangeGeneration
    from engine.services import record_model_observations
    from shared.enums import RangeSource
    from shared.range_instantiation_policy import InstantiationPurpose
    from workspaces.services import resolve_personal_workspace

    from ..engine.test_operation_input_raes import _plan

    owner, request, instance = setup_launch(django_user_model, settings, owner=create_managed_warm_user())
    from shared.model_access import seal_catalog

    payload = settings.MODEL_ACCESS_CATALOG.model_dump(mode="json")
    payload["price_schedules"][0]["valid_until"] = "2099-01-01T00:00:00Z"
    settings.MODEL_ACCESS_CATALOG = seal_catalog(payload)
    _, _, observations = allocation_inputs(django_user_model)
    observations = (observations[0].model_copy(update={"catalog_digest": settings.MODEL_ACCESS_CATALOG.digest}),)
    record_model_observations(settings.MODEL_ACCESS_CATALOG, lambda _: observations)
    claimant = django_user_model.objects.create_user(username="model-warm-claimant")
    workspace_id = resolve_personal_workspace(claimant).workspace_id
    Range.objects.filter(uuid=request.range_id).update(
        range_config=_plan(),
        range_backend="gce",
        instantiation_purpose="training",
    )
    instance.expires_at = instance.maximum_expires_at = None
    instance.save(update_fields=["expires_at", "maximum_expires_at"])
    generation = WarmRangeGeneration.objects.create(
        request_id=request.request_id,
        range=Range.objects.get(uuid=request.range_id),
        state="provisioning",
        bucket_id="model-warm",
        operation_id=request.operation_id,
        compatibility_digest="sha256:" + "a" * 64,
        effective_policy_fingerprint="sha256:" + "b" * 64,
        backend="gce",
        range_source="mission_control",
        capacity_partition="default",
        capacity_scope_ref=uuid4(),
        capacity_draw_key=uuid4(),
        idle_deadline=request.window_end,
    )
    with transaction.atomic():
        prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
        enqueue_provisioner_launch(["raes-range", "provision", "--request-id", str(request.request_id)])
    preparation = ModelAllocation.objects.get()
    assert preparation.grant.state == "pending"
    assert preparation.snapshot["request"]["preparation_authority"] == {
        "owner": "engine",
        "reference": f"warm-generation:{generation.uuid}",
    }
    original_snapshot = preparation.snapshot
    if overlay_removed:
        from cms.models import ScenarioModelNeeds

        ScenarioModelNeeds.objects.all().delete()
    owner.refresh_from_db()
    assert not owner.is_active and not owner.has_usable_password()
    generation.state = "ready"
    generation.save(update_fields=["state"])
    preparation.grant.refresh_from_db()
    assert preparation.grant.state == "pending"
    if exhausted:
        from django.utils import timezone

        observations = (
            observations[0].model_copy(update={"usage": observations[0].limit, "observed_at": timezone.now()}),
        )
        record_model_observations(settings.MODEL_ACCESS_CATALOG, lambda _: observations)
    claim = WarmClaimRequest(
        user=claimant,
        scenario="scn",
        package_digest=instance.model_package_digest,
        lock_digest="sha256:" + "c" * 64,
        backend="gce",
        instantiation_purpose=InstantiationPurpose.LIVE_FIRE,
        range_source=RangeSource.MISSION_CONTROL,
        workspace_id=workspace_id,
        egress_mode="status-quo",
        request_id=uuid4(),
    )
    if exhausted:
        with pytest.raises(ContractError, match=r"allocation\.capacity_unavailable"):
            _run_atomic_claim(claim, [(generation.bucket_id, generation.compatibility_digest)])
        generation.refresh_from_db()
        instance.refresh_from_db()
        assert generation.state == "ready"
        assert generation.claimed_by_request_id is None
        assert instance.user_id == owner.pk
        assert instance.expires_at is None
        assert ModelAllocation.objects.count() == 1
        preparation.grant.refresh_from_db()
        assert preparation.grant.state == "pending"
        assert ProvisionerLaunchIntent.objects.count() == 1
    else:
        result = _run_atomic_claim(claim, [(generation.bucket_id, generation.compatibility_digest)])
        assert result.activation_enqueued
        instance.refresh_from_db()
        assert instance.user_id == claimant.pk
        activation = ModelAllocation.objects.exclude(pk=preparation.pk).get()
        assert activation.snapshot["request"]["owner_ref"]["reference"] == f"user:{claimant.pk}"
        assert activation.snapshot["request"]["preparation_authority"] is None
        assert activation.grant.state == "pending"
        preparation.refresh_from_db()
        preparation.grant.refresh_from_db()
        assert preparation.grant.state == "revoked"
        assert preparation.released_at is not None
        assert preparation.snapshot == original_snapshot
        assert activation.grant.grant_epoch > preparation.grant.grant_epoch
        assert ProvisionerLaunchIntent.objects.count() == 2


def test_disabled_owner_cannot_publish_allowed_projection(django_user_model, settings):
    from cms.services._model_allocation import prepare_model_access_for_dispatch

    actor, request, _ = setup_launch(django_user_model, settings)
    actor.is_active = False
    actor.save(update_fields=["is_active"])
    with pytest.raises(ContractError, match=r"allocation\.authority_unavailable"):
        prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    assert not ModelLaunchPreparationRecord.objects.exists()


def test_launch_refreshes_real_user_selector_and_applies_its_spend_account(django_user_model, settings):
    from datetime import timedelta

    from django.db import transaction
    from django.utils import timezone

    from cms.services._model_allocation import prepare_model_access_for_dispatch
    from config.model_access_sharing import publish_model_access_binding
    from engine.services import invalidate_sharing_authority, record_model_observations
    from engine.services._model_allocation_launch import allocate_launch_models
    from shared.model_access import SharingFacet, SharingPool, seal_sharing_binding
    from shared.model_access.reservation import ModelQuotaObservation

    from ..engine.services.test_sharing import _binding_dto, _pool_dto

    actor, request, _ = setup_launch(django_user_model, settings)
    catalog = settings.MODEL_ACCESS_CATALOG
    binding = _binding_dto(facets=(SharingFacet.SPEND,)).model_dump(mode="json")
    binding["selector"] = {"kind": "user", "ids": [str(actor.pk)]}
    publish_model_access_binding(
        actor=actor,
        deployment_id=catalog.deployment_id,
        catalog=catalog,
        binding=seal_sharing_binding(binding),
        pool=SharingPool.model_validate(_pool_dto()),
        expected_definition_revision=0,
    )
    invalidate_sharing_authority(
        {
            "deployment_id": catalog.deployment_id,
            "authority_refs": [request.owner_ref.model_dump(mode="json")],
            "state": "unknown",
            "reason": "owner-changed",
        }
    )
    now = timezone.now()
    record_model_observations(
        catalog,
        lambda _: [
            ModelQuotaObservation(
                quota_pool_id="vertex-tokens-eu",
                catalog_digest=catalog.digest,
                source="observed_provider",
                observed_at=now,
                valid_until=now + timedelta(minutes=5),
                limit=1000000,
                usage=0,
                healthy_shard_ids=("vertex-primary",),
            )
        ],
    )
    with transaction.atomic():
        prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
        (allocation,) = allocate_launch_models(
            {"resource": "raes-range", "operation": "provision", "request_id": str(request.request_id)},
            request.operation_id,
        )
    assert allocation.snapshot["effective_policy"]["spend_account_refs"] == ["acct-shared"]


def test_credential_deadline_is_session_window_not_membership_freshness(django_user_model, settings):
    """The allocation deadline (and therefore the credential hard expiry) is the
    range session window, never the ~5-minute membership freshness window.

    Regression for the guest model-access credential dying mid-provision: the
    membership freshness is a re-validation interval enforced continuously by the
    authority-fence pins on every exchange/refresh/authenticate, not a hard cap on
    the credential. A GCE range that takes longer than the freshness window to boot
    and enroll must still receive a usable, session-length credential.
    """
    from datetime import timedelta

    from django.db import transaction
    from django.utils import timezone

    from cms.services._model_allocation import prepare_model_access_for_dispatch
    from config.model_access_sharing import publish_model_access_binding
    from engine.services import record_model_observations
    from engine.services._model_allocation_launch import allocate_launch_models
    from shared.model_access import SharingFacet, SharingPool, seal_sharing_binding
    from shared.model_access.reservation import ModelQuotaObservation

    from ..engine.services.test_sharing import _binding_dto, _pool_dto

    actor, request, _ = setup_launch(django_user_model, settings)
    catalog = settings.MODEL_ACCESS_CATALOG
    binding = _binding_dto(facets=(SharingFacet.SPEND,)).model_dump(mode="json")
    binding["selector"] = {"kind": "user", "ids": [str(actor.pk)]}
    publish_model_access_binding(
        actor=actor,
        deployment_id=catalog.deployment_id,
        catalog=catalog,
        binding=seal_sharing_binding(binding),
        pool=SharingPool.model_validate(_pool_dto()),
        expected_definition_revision=0,
    )
    now = timezone.now()
    # Membership freshness is deliberately far nearer than the session window, so a
    # deadline equal to window_end proves fresh_until is not capping the credential.
    assert request.window_end > now + timedelta(minutes=6)
    record_model_observations(
        catalog,
        lambda _: [
            ModelQuotaObservation(
                quota_pool_id="vertex-tokens-eu",
                catalog_digest=catalog.digest,
                source="observed_provider",
                observed_at=now,
                valid_until=now + timedelta(minutes=5),
                limit=1000000,
                usage=0,
                healthy_shard_ids=("vertex-primary",),
            )
        ],
    )
    with transaction.atomic():
        prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
        (allocation,) = allocate_launch_models(
            {"resource": "raes-range", "operation": "provision", "request_id": str(request.request_id)},
            request.operation_id,
        )
    assert allocation.deadline == request.window_end


def test_resume_reauthorizes_after_status_change_and_commits_new_grant(django_user_model, settings):
    from django.db import transaction

    from cms.services._model_allocation import prepare_model_access_for_dispatch, resume_model_range
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ModelAllocation, Range
    from engine.services import record_model_observations
    from engine.services._model_allocation_lifecycle import revoke_model_generation

    from ..engine.services.test_model_allocation import allocation_inputs
    from ..engine.test_operation_input_raes import _plan

    _, request, _ = setup_launch(django_user_model, settings)
    settings.CLOUD_PROVIDER = "aws"
    settings.ENGINE_TASK_CLUSTER = "test-cluster"
    settings.ENGINE_TASK_DEFINITION = "test-taskdef"
    settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
    settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-test"
    _, _, observations = allocation_inputs(django_user_model)
    record_model_observations(settings.MODEL_ACCESS_CATALOG, lambda _: observations)
    Range.objects.filter(uuid=request.range_id).update(
        range_config=_plan(),
        range_backend="gce",
        instantiation_purpose="training",
        provisioner_operation_id=None,
        provisioner_operation="",
    )
    with transaction.atomic():
        prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
        enqueue_provisioner_launch(["raes-range", "provision", "--request-id", str(request.request_id)])
    original = ModelAllocation.objects.get()
    row = Range.objects.get(uuid=request.range_id)
    revoke_model_generation(row.uuid, operation_id=original.operation_id)
    # Exercise reauthorization on the supported legacy power path. Native RAES
    # resume is separately required to reject without minting a replacement grant.
    row.status = Range.Status.PAUSED
    row.range_config = {}
    row.save(update_fields=["status", "range_config"])
    assert resume_model_range(request.request_id)
    replacement = ModelAllocation.objects.exclude(pk=original.pk).get()
    assert replacement.operation_id != original.operation_id
    assert replacement.grant.grant_epoch > original.grant.grant_epoch
    original.refresh_from_db()
    assert original.released_at is not None


def test_unleased_warm_preparation_uses_real_warm_scope(django_user_model, settings):
    from uuid import uuid4

    from cms.services._model_allocation import prepare_model_access_for_dispatch
    from cms.services._warm_pool_reconcile import create_managed_warm_user
    from engine.models import Range, WarmRangeGeneration

    _, request, instance = setup_launch(django_user_model, settings, owner=create_managed_warm_user())
    instance.expires_at = instance.maximum_expires_at = None
    instance.save(update_fields=["expires_at", "maximum_expires_at"])
    scope_id, draw = uuid4(), uuid4()
    WarmRangeGeneration.objects.create(
        request_id=request.request_id,
        range=Range.objects.get(uuid=request.range_id),
        bucket_id="model-warm",
        compatibility_digest="sha256:" + "a" * 64,
        effective_policy_fingerprint="sha256:" + "b" * 64,
        backend="gce",
        range_source="mission_control",
        capacity_partition="default",
        capacity_scope_ref=scope_id,
        capacity_draw_key=draw,
        idle_deadline=request.window_end,
    )
    prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    scope = ModelLaunchPreparationRecord.objects.get(request_id=request.request_id).intent["scope"]
    assert scope["kind"] == "warm"
    assert scope["scope_id"] == str(scope_id)
    assert scope["draw_key"] == str(draw)
