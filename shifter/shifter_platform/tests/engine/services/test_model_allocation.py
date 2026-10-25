"""Durable, fail-closed M03 allocation behavior at the Engine service boundary."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from engine.models import Range, Request, SharingAuthorityFence
from engine.services import publish_authority_fence
from shared.model_access import ContractError, OwnedReference, seal_catalog

from .test_model_admission import _catalog, _demand, _need

pytestmark = pytest.mark.django_db(transaction=True)


def test_zero_egress_range_cannot_allocate_external_model(django_user_model):
    inputs = allocation_inputs(django_user_model)
    Range.objects.filter(uuid=inputs[1].range_id).update(egress_mode="none")
    with pytest.raises(ContractError, match=r"allocation\.egress_incompatible"):
        allocate(inputs)


def allocation_inputs(django_user_model, *, user=None):
    """Use canonical catalog/need fixtures and actual range/generation ownership."""
    from shared.model_access.reservation import ModelAllocationRequest, ModelQuotaObservation

    now = timezone.now()
    catalog = _catalog()
    user = user or django_user_model.objects.create_user(username=f"allocation-{uuid4()}")
    request = Request.objects.create(request_id=uuid4(), request_type="range", user=user)
    operation_id = uuid4()
    range_obj = Range.objects.create(
        user=user,
        request=request,
        workspace_id=1,
        cms_user_id=user.pk,
        provisioner_operation="raes-range:provision",
        provisioner_operation_id=operation_id,
        status=Range.Status.PROVISIONING,
    )
    authority = {"owner": "management", "reference": f"user:{user.pk}"}
    from engine.services._sharing_authority import _refresh_authority_fences

    with transaction.atomic():
        _refresh_authority_fences(
            deployment_id=catalog.deployment_id,
            authority_refs=(OwnedReference.model_validate(authority),),
        )
        fence = SharingAuthorityFence.objects.get(
            deployment_id=catalog.deployment_id,
            authority_owner=authority["owner"],
            authority_reference=authority["reference"],
        )
    candidate = ModelAllocationRequest(
        deployment_id=catalog.deployment_id,
        request_id=request.request_id,
        operation_id=operation_id,
        range_id=range_obj.uuid,
        draw_key=uuid4(),
        owner_ref=authority,
        subject_ref={"owner": "engine", "reference": f"range:{range_obj.uuid}"},
        scope_kind="standalone",
        scope_id=request.request_id,
        need=_need(),
        demand=_demand(),
        window_start=now,
        window_end=now + timedelta(hours=1),
        authority_revisions=({"authority_ref": authority, "authority_revision": fence.authority_revision},),
    )
    observation = ModelQuotaObservation(
        quota_pool_id=catalog.quota_pools[0].quota_pool_id,
        catalog_digest=catalog.digest,
        observed_at=now,
        valid_until=now + timedelta(minutes=5),
        source="observed_provider",
        limit=1000000,
        usage=0,
        healthy_shard_ids=("vertex-primary",),
    )
    return catalog, candidate, (observation,)


def allocate(inputs):
    from engine.services._model_allocation import allocate_model_access

    catalog, request, observations = inputs
    return allocate_model_access(request, catalog=catalog, observations=observations)


def test_allocation_pins_complete_map_and_pending_grant(django_user_model):
    catalog, request, observations = allocation_inputs(django_user_model)
    result = allocate((catalog, request, observations))
    assert result.alias_shards == {"coding-main": "vertex-primary"}
    assert result.operation_id == request.operation_id
    assert result.snapshot["catalog"]["digest"] == catalog.digest
    assert result.snapshot["need"]["scenario_digest"] == request.need.scenario_digest
    assert result.grant.state == "pending"
    assert result.grant.grant_epoch == 1
    assert result.draws.count() == 1
    assert result.draws.get().amount == request.demand.per_participant_input_tokens


@pytest.mark.parametrize("grant_state", ["pending", "active"])
def test_retry_reuses_record_after_catalog_change(django_user_model, grant_state):
    catalog, request, observations = allocation_inputs(django_user_model)
    original = allocate((catalog, request, observations))
    original.grant.state = grant_state
    original.grant.save(update_fields=["state"])
    changed = catalog.model_dump(mode="json")
    changed["shards"][0]["weight"] = 2
    replay = allocate((seal_catalog(changed), request, ()))
    assert replay.pk == original.pk
    assert replay.draws.count() == 1
    assert replay.snapshot == original.snapshot


def test_changed_request_is_not_an_idempotent_retry(django_user_model):
    catalog, request, observations = allocation_inputs(django_user_model)
    original = allocate((catalog, request, observations))
    changed = request.model_copy(update={"draw_key": uuid4()})
    with pytest.raises(ContractError, match=r"allocation\.intent_conflict"):
        allocate((catalog, changed, observations))
    assert original.draws.count() == 1


@pytest.mark.parametrize(
    ("change", "error_code"),
    [
        ("stale", r"allocation\.invalid_input"),
        ("future", r"allocation\.invalid_input"),
        ("unhealthy", r"allocation\.capacity_unavailable"),
        ("exhausted", r"allocation\.capacity_unavailable"),
        ("missing", r"allocation\.capacity_unavailable"),
    ],
)
def test_unusable_observation_reserves_nothing(django_user_model, change, error_code):
    from engine.models import ModelAllocation, ModelCapacityReservation

    catalog, request, observations = allocation_inputs(django_user_model)
    observation = observations[0]
    updates = {
        "stale": {"valid_until": request.window_start - timedelta(seconds=1)},
        "future": {"observed_at": request.window_end},
        "unhealthy": {"healthy_shard_ids": ()},
        "exhausted": {"usage": observation.limit},
    }
    observations = () if change == "missing" else (observation.model_copy(update=updates[change]),)
    with pytest.raises(ContractError, match=error_code):
        allocate((catalog, request, observations))
    assert not ModelAllocation.objects.exists()
    assert not ModelCapacityReservation.objects.exists()


def test_revoked_subject_cannot_allocate_without_sharing(django_user_model):
    catalog, request, observations = allocation_inputs(django_user_model)
    publish_authority_fence(
        deployment_id=catalog.deployment_id,
        authority_ref=request.owner_ref,
        authority_revision=2,
        state="revoked",
    )
    with pytest.raises(ContractError, match=r"allocation\.authority"):
        allocate((catalog, request, observations))


def test_distinct_workloads_extend_one_parent_without_reusing_each_others_budget(django_user_model):
    catalog, request, observations = allocation_inputs(django_user_model)
    first = allocate((catalog, request, observations))
    second_request = request.model_copy(
        update={
            "need": request.need.model_copy(update={"workload_role": "assistant"}),
            "demand": request.demand.model_copy(update={"workload_role": "assistant"}),
        }
    )
    second = allocate((catalog, second_request, observations))
    assert first.draws.get().reservation_id == second.draws.get().reservation_id
    assert second.draws.get().reservation.amount == 8000


def test_success_metric_is_emitted_only_after_enclosing_commit(django_user_model, caplog):
    import logging

    from django.db import transaction

    inputs = allocation_inputs(django_user_model)
    with caplog.at_level(logging.INFO, logger="engine.services._model_allocation"):
        with transaction.atomic():
            allocate(inputs)
            assert not any(getattr(record, "model_access_outcome", None) for record in caplog.records)
        recorded = [record for record in caplog.records if getattr(record, "model_access_outcome", None)]
        assert len(recorded) == 1
        assert recorded[0].model_access_outcome == "admitted"
        assert recorded[0].model_access_namespace == "Shifter/ModelAccess"
