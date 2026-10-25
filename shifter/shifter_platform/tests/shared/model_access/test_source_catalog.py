"""Source revision and selected-provider pricing are immutable admission inputs."""

from copy import deepcopy
from uuid import UUID

import pytest
from test_account_definitions import v3_payload

from shared.model_access import ContractError, load_catalog_json, seal_catalog


def v4_payload():
    payload = v3_payload()
    payload["contract_version"] = "model-access-policy/v4"
    payload["source_bindings"] = []
    for index, shard in enumerate(payload["shards"]):
        price = deepcopy(payload["price_schedules"][0])
        price["price_schedule_id"] = f"source-price-{index}"
        price["prices"][0]["price_micro_units"] = 100 + index
        payload["price_schedules"].append(price)
        shard["credential_ref"] = {"owner": "broker", "reference": f"source:{UUID(int=index + 1)}:1"}
        payload["source_bindings"].append(
            {
                "shard_id": shard["shard_id"],
                "source_id": str(UUID(int=index + 1)),
                "source_revision": 1,
                "credential_revision": 1,
                "price_schedule_id": price["price_schedule_id"],
            }
        )
    return payload


def test_mixed_sources_pin_different_prices_without_changing_old_contracts():
    old = seal_catalog(v3_payload())
    assert load_catalog_json(old.model_dump_json()) == old
    catalog = seal_catalog(v4_payload())
    alias = catalog.aliases[0]
    for binding in catalog.source_bindings:
        if binding.shard_id in alias.eligible_shard_ids:
            price = catalog.price_for_alias(alias.logical_alias, binding.shard_id)
            assert price.price_schedule_id == binding.price_schedule_id
            assert price.price_schedule_id != alias.price_schedule_id
    assert load_catalog_json(catalog.model_dump_json()) == catalog
    assert (
        old.price_for_alias(old.aliases[0].logical_alias, old.aliases[0].eligible_shard_ids[0]).price_schedule_id
        == old.aliases[0].price_schedule_id
    )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown_price", "unpriced", "unknown_shard"])
def test_invalid_source_price_binding_denies_publication(mutation):
    payload = v4_payload()
    if mutation == "missing":
        payload["source_bindings"].pop()
    elif mutation == "duplicate":
        payload["source_bindings"].append(deepcopy(payload["source_bindings"][0]))
    elif mutation == "unknown_price":
        payload["source_bindings"][0]["price_schedule_id"] = "unknown"
    elif mutation == "unpriced":
        payload["price_schedules"][-1]["prices"][0]["component"] = "image"
    else:
        payload["source_bindings"][0]["shard_id"] = "unknown"
    with pytest.raises(ContractError):
        seal_catalog(payload)


def test_v3_cannot_silently_accept_source_pricing():
    payload = v4_payload()
    payload["contract_version"] = "model-access-policy/v3"
    with pytest.raises(ContractError):
        seal_catalog(payload)
