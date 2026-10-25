"""Versioned provider-pool membership is explicit, closed and digest-bound."""

import json

import pytest
from test_contract import _catalog_payload

from shared.model_access import ContractError, load_catalog_json, seal_catalog, validate_catalog

_PRE_V2_V1_DIGEST = "sha256:e519d0e2ad1469657a5387d012071e9fe65b8d478a90d870a5a0a91c418c444b"


def v2_payload():
    payload = _catalog_payload()
    payload.update(
        contract_version="model-access-policy/v2",
        provider_pools=[
            {"provider_pool_id": "classroom", "shard_ids": ["vertex-primary"]},
        ],
    )
    return payload


def test_v2_roundtrip_pins_provider_pool_membership():
    catalog = seal_catalog(v2_payload())
    assert catalog.provider_pools[0].shard_ids == ("vertex-primary",)
    assert load_catalog_json(catalog.model_dump_json()) == catalog
    changed = catalog.model_dump(mode="json")
    changed["provider_pools"][0]["provider_pool_id"] = "other"
    with pytest.raises(ContractError, match=r"contract\.digest_mismatch"):
        validate_catalog(changed)


@pytest.mark.parametrize(
    "pools",
    [
        [{"provider_pool_id": "classroom", "shard_ids": []}],
        [{"provider_pool_id": "classroom", "shard_ids": ["unknown"]}],
        [{"provider_pool_id": "classroom", "shard_ids": ["vertex-primary", "vertex-primary"]}],
        [{"provider_pool_id": "classroom", "shard_ids": ["vertex-primary"]}] * 2,
    ],
)
def test_invalid_or_ambiguous_provider_membership_denies(pools):
    payload = v2_payload()
    payload["provider_pools"] = pools
    with pytest.raises(ContractError, match=r"contract\.validation"):
        seal_catalog(payload)


def test_v1_digest_and_schema_remain_unchanged():
    catalog = seal_catalog(_catalog_payload())
    assert catalog.digest == _PRE_V2_V1_DIGEST
    assert "provider_pools" not in json.loads(catalog.model_dump_json())
    assert validate_catalog(catalog.model_dump(mode="json")) == catalog
    payload = catalog.model_dump(mode="json")
    payload["provider_pools"] = []
    with pytest.raises(ContractError, match=r"contract\.validation"):
        seal_catalog(payload)
