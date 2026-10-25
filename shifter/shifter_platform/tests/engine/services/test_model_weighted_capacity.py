"""Weighted event sources reserve one cohort across independent real quotas."""

from copy import deepcopy
from uuid import uuid4

import pytest

from engine.models import ModelAllocation, ModelCapacityReservation
from shared.model_access import ContractError, seal_catalog
from shared.model_access.core_models import AllocationStrategy

from .test_model_allocation import allocate, allocation_inputs
from .test_model_request_accounting import seal_v3_catalog

pytestmark = pytest.mark.django_db(transaction=True)


def cohort_inputs(django_user_model, *, concurrency=4, weights=(1, 1), shared_quota=False):
    _, first, readings = allocation_inputs(django_user_model)
    payload = seal_v3_catalog(first.deployment_id).model_dump(mode="json")
    payload["contract_version"] = "model-access-policy/v4"
    weighted = AllocationStrategy.WEIGHTED_RENDEZVOUS_V1
    payload["profiles"][0]["allowed_strategies"] = [weighted]
    payload["shards"][0]["weight"] = weights[0]
    other = deepcopy(payload["shards"][0])
    other.update(shard_id="vertex-secondary", weight=weights[1])
    if not shared_quota:
        pool = deepcopy(payload["quota_pools"][0])
        pool.update(quota_pool_id="other-account", provider_quota_identity="project:models-b/region:europe-west4")
        payload["quota_pools"].append(pool)
        other["quota_pool_ids"] = [pool["quota_pool_id"]]
    payload["shards"].append(other)
    payload["aliases"][0].update(strategy=weighted, eligible_shard_ids=[s["shard_id"] for s in payload["shards"]])
    payload["source_bindings"] = [
        {
            "shard_id": s["shard_id"],
            "source_id": None,
            "source_revision": 1,
            "credential_revision": 1,
            "price_schedule_id": None,
        }
        for s in payload["shards"]
    ]
    catalog = seal_catalog(payload)
    scope_id = uuid4()
    requests = []
    for index in range(concurrency + 1):
        candidate = first if index == 0 else allocation_inputs(django_user_model)[1]
        requests.append(
            candidate.model_copy(
                update={
                    "scope_kind": "event",
                    "scope_id": scope_id,
                    "window_start": first.window_start,
                    "window_end": first.window_end,
                    "need": candidate.need.model_copy(update={"allowed_strategies": (weighted,)}),
                    "demand": candidate.demand.model_copy(
                        update={"allowed_strategy": weighted, "expected_concurrency": concurrency}
                    ),
                }
            )
        )
    observations = tuple(
        readings[0].model_copy(
            update={
                "quota_pool_id": pool.quota_pool_id,
                "catalog_digest": catalog.digest,
                "limit": 8000,
                "healthy_shard_ids": tuple(s.shard_id for s in catalog.shards),
            }
        )
        for pool in catalog.quota_pools
    )
    return catalog, requests, observations


@pytest.mark.parametrize(
    ("concurrency", "weights", "ceilings"), [(4, (1, 1), (8000, 8000)), (5, (2, 1), (12000, 8000))]
)
def test_cohort_combines_accounts_that_cannot_individually_fund_the_event(
    django_user_model, concurrency, weights, ceilings
):
    catalog, requests, observations = cohort_inputs(django_user_model, concurrency=concurrency, weights=weights)
    # Catalog pools normalize by id: the second account sorts before the first.
    observations = tuple(
        item.model_copy(update={"limit": ceilings[1] if item.quota_pool_id == "other-account" else ceilings[0]})
        for item in observations
    )
    first = allocate((catalog, requests[0], observations))
    assert first.draws.count() == 1
    assert sorted(ModelCapacityReservation.objects.values_list("amount", flat=True)) == sorted(ceilings)
    for candidate in requests[1:concurrency]:
        allocate((catalog, candidate, observations))
    assert sorted(ModelCapacityReservation.objects.values_list("consumed", flat=True)) == sorted(ceilings)
    with pytest.raises(ContractError, match="capacity_unavailable"):
        allocate((catalog, requests[concurrency], observations))
    assert ModelAllocation.objects.count() == concurrency


def test_cohort_does_not_manufacture_capacity_when_sources_share_a_real_quota(django_user_model):
    catalog, requests, observations = cohort_inputs(django_user_model, shared_quota=True)
    with pytest.raises(ContractError, match="capacity_unavailable"):
        allocate((catalog, requests[0], observations))
    assert not ModelCapacityReservation.objects.exists()


def test_cohort_reserves_all_accounts_atomically_before_first_draw(django_user_model):
    catalog, requests, observations = cohort_inputs(django_user_model)
    observations = (observations[0], observations[1].model_copy(update={"limit": 7999}))
    with pytest.raises(ContractError, match="capacity_unavailable"):
        allocate((catalog, requests[0], observations))
    assert not ModelCapacityReservation.objects.exists()


def test_two_sources_on_one_quota_reserve_the_cohort_only_once(django_user_model):
    catalog, requests, observations = cohort_inputs(django_user_model, shared_quota=True)
    observations = (observations[0].model_copy(update={"limit": 16000}),)
    for candidate in requests[:4]:
        allocate((catalog, candidate, observations))
    parent = ModelCapacityReservation.objects.get()
    assert parent.amount == parent.consumed == 16000


def test_small_event_does_not_reserve_fractional_slots_on_every_source(django_user_model):
    catalog, requests, observations = cohort_inputs(django_user_model, concurrency=1)
    allocation = allocate((catalog, requests[0], observations))
    assert allocation.draws.get().reservation.amount == 4000
    assert ModelCapacityReservation.objects.count() == 1
