"""Lifecycle routing must follow the durable package snapshot and native executor."""

import pytest

from cms.exceptions import CMSError
from cms.models import ScenarioModelNeeds
from cms.services._model_allocation import needs_model_preparation, prepare_model_access_for_dispatch
from engine.models import (
    ModelAllocation,
    ModelLaunchPreparationRecord,
    ModelQuotaReading,
    ProvisionerLaunchIntent,
    Range,
)
from engine.services import record_model_observations

from ..engine.services.test_model_allocation import allocation_inputs
from ..engine.test_operation_input_raes import _plan
from .test_model_allocation_dispatch import setup_launch

pytestmark = pytest.mark.django_db(transaction=True)


def paused_launch(django_user_model, settings, *, native=False):
    owner, request, instance = setup_launch(django_user_model, settings)
    _, _, observations = allocation_inputs(django_user_model)
    record_model_observations(settings.MODEL_ACCESS_CATALOG, lambda _: observations)
    prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    Range.objects.filter(uuid=request.range_id).update(
        status="paused", range_config=_plan() if native else {}, range_backend="gce"
    )
    instance.status = "paused"
    instance.save(update_fields=["status"])
    settings.CLOUD_PROVIDER = "aws"
    settings.LOCAL_PROVISIONER = None
    settings.ENGINE_TASK_CLUSTER = "test-cluster"
    settings.ENGINE_TASK_DEFINITION = "test-taskdef"
    settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
    settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-test"
    return owner, request, instance


def test_removed_overlay_does_not_erase_durable_preparation(django_user_model, settings):
    from cms.services._model_allocation import resume_model_range

    _, request, _ = paused_launch(django_user_model, settings)
    original = ModelLaunchPreparationRecord.objects.get().intent["needs"]
    ScenarioModelNeeds.objects.all().delete()
    assert needs_model_preparation(request.request_id)
    assert resume_model_range(request.request_id)
    assert ModelAllocation.objects.get().snapshot["need"] == original[0]


def test_model_resume_uses_legacy_power_operation(django_user_model, settings):
    from cms.services._model_allocation import resume_model_range

    _, request, _ = paused_launch(django_user_model, settings)
    assert resume_model_range(request.request_id)
    intent = ProvisionerLaunchIntent.objects.get()
    assert intent.payload["resource"] == "range"
    assert intent.payload["operation"] == "resume"
    assert ModelAllocation.objects.get().operation_id == intent.operation_id


def test_denied_resume_reverts_both_cms_and_engine(django_user_model, settings):
    from cms.services import resume_range_by_request_id

    owner, request, instance = paused_launch(django_user_model, settings)
    ModelQuotaReading.objects.all().delete()
    with pytest.raises(CMSError):
        resume_range_by_request_id(owner, str(request.request_id))
    instance.refresh_from_db()
    assert instance.status == "paused"
    assert Range.objects.get(uuid=request.range_id).status == "paused"
    assert not ProvisionerLaunchIntent.objects.exists()
    assert not ModelAllocation.objects.exists()


@pytest.mark.parametrize("policy", ["disabled", "missing"])
def test_optional_policy_removal_cannot_reuse_old_catalog(django_user_model, settings, policy):
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ModelOptionalAbsence
    from engine.services import record_model_observations

    _, request, _ = setup_launch(django_user_model, settings, required=False)
    catalog = settings.MODEL_ACCESS_CATALOG
    _, _, observations = allocation_inputs(django_user_model)
    record_model_observations(catalog, lambda _: observations)
    settings.MODEL_ACCESS_ENABLED = False
    if policy == "missing":
        settings.MODEL_ACCESS_CATALOG = None
    prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    command = ["raes-range", "provision", "--request-id", str(request.request_id)]
    first = enqueue_provisioner_launch(command)
    assert not ModelAllocation.objects.exists()
    assert ModelOptionalAbsence.objects.get().reason == "allocation.policy_unavailable"
    assert needs_model_preparation(request.request_id)
    record = ModelLaunchPreparationRecord.objects.get()
    assert record.catalog is None

    settings.MODEL_ACCESS_ENABLED = True
    settings.MODEL_ACCESS_CATALOG = catalog
    prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    assert enqueue_provisioner_launch(command) == first
    assert not ModelAllocation.objects.exists()


def test_native_model_resume_cannot_allocate_or_dispatch(django_user_model, settings):
    from cms.services._model_allocation import resume_model_range

    _, request, _ = paused_launch(django_user_model, settings, native=True)
    assert resume_model_range(request.request_id) is False
    assert Range.objects.get(uuid=request.range_id).status == "paused"
    assert not ProvisionerLaunchIntent.objects.exists()
    assert not ModelAllocation.objects.exists()
