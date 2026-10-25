"""Provider identity restrictions constrain actual allocation, not only previews."""

from copy import deepcopy

import pytest

from engine.models import ModelAllocation
from shared.model_access import AllocationStrategy, ContractError, SharingFacet, seal_catalog

from .test_model_allocation import allocate, allocation_inputs
from .test_sharing import _binding_dto, _pool_dto, _publish, _services

pytestmark = pytest.mark.django_db(transaction=True)


def provider_inputs(django_user_model):
    catalog, request, observations = allocation_inputs(django_user_model)
    payload = catalog.model_dump(mode="json")
    secondary = deepcopy(payload["shards"][0])
    secondary["shard_id"] = "vertex-secondary"
    payload["shards"].append(secondary)
    payload["aliases"][0].update(
        strategy="weighted-rendezvous-v1", eligible_shard_ids=["vertex-primary", "vertex-secondary"]
    )
    payload.update(
        contract_version="model-access-policy/v2",
        provider_pools=[
            {"provider_pool_id": "classroom", "shard_ids": ["vertex-secondary"]},
        ],
    )
    catalog = seal_catalog(payload)
    request = request.model_copy(
        update={
            "subject_ref": request.subject_ref.model_copy(update={"owner": "deployment"}),
            "need": request.need.model_copy(
                update={"allowed_strategies": (AllocationStrategy.WEIGHTED_RENDEZVOUS_V1,)}
            ),
            "demand": request.demand.model_copy(update={"allowed_strategy": AllocationStrategy.WEIGHTED_RENDEZVOUS_V1}),
        }
    )
    _publish(
        _services(),
        catalog,
        _binding_dto(facets=(SharingFacet.PROVIDER_IDENTITY,)),
        _pool_dto(provider_pool_ref="classroom"),
        members=(request.subject_ref.reference,),
    )
    observations = (
        observations[0].model_copy(
            update={"catalog_digest": catalog.digest, "healthy_shard_ids": ("vertex-secondary",)}
        ),
    )
    return catalog, request, observations


def test_provider_pool_limits_the_selected_shard(django_user_model):
    inputs = provider_inputs(django_user_model)
    allocation = allocate(inputs)
    assert allocation.alias_shards == {"coding-main": "vertex-secondary"}
    assert allocation.snapshot["catalog"]["provider_pools"] == [
        {"provider_pool_id": "classroom", "shard_ids": ["vertex-secondary"]},
    ]
    assert allocate(inputs).pk == allocation.pk


def test_unavailable_pool_member_cannot_fall_back_to_unrestricted_shard(django_user_model):
    catalog, request, observations = provider_inputs(django_user_model)
    observations = (observations[0].model_copy(update={"healthy_shard_ids": ("vertex-primary",)}),)
    with pytest.raises(ContractError, match=r"allocation\.capacity_unavailable"):
        allocate((catalog, request, observations))
    assert not ModelAllocation.objects.exists()
