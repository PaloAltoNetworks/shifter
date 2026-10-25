"""User choices compile into the existing allocator without replacing policy."""

from uuid import UUID

import pytest
from test_account_definitions import v3_payload

from shared.model_access import ContractError, seal_catalog
from shared.model_access.sources import ModelSourceConfiguration, ModelSourceSelection


def source(project="models-example"):
    return ModelSourceConfiguration.model_validate(
        {
            "name": "Workshop",
            "provider": "vertex-v1",
            "authentication": "workload-identity",
            "project": project,
            "principal": f"model-invoke@{project}.iam.gserviceaccount.com",
            "count_region": "us",
            "region": "europe-west4",
            "model": "publishers/anthropic/models/claude-synthetic@20260901",
            "quota_identity": "account:workshop",
            "context_window_tokens": 200_000,
            "tokens_per_minute": 100_000,
            "input_price_per_million": 3_000_000,
            "output_price_per_million": 15_000_000,
            "price_valid_until": "2027-10-01T00:00:00Z",
            "allow_organization_members": True,
        }
    )


def base_catalog():
    payload = v3_payload()
    # This synthetic profile explicitly permits weighted allocation.
    payload["profiles"][0]["allowed_strategies"] = ["fixed-v1", "weighted-rendezvous-v1"]
    return seal_catalog(payload)


def test_mixed_choice_retains_budget_policy_and_coalesces_real_quota():
    from shared.model_access.source_catalog import compile_source_catalog

    base = base_catalog()
    alias = base.aliases[0].logical_alias
    choices = ModelSourceSelection.model_validate(
        {
            "aliases": [
                {
                    "logical_alias": alias,
                    "sources": [
                        {"source_id": str(UUID(int=1)), "revision": 1, "weight": 1},
                        {"source_id": str(UUID(int=2)), "revision": 2, "weight": 3},
                    ],
                }
            ]
        }
    )
    result = compile_source_catalog(base, choices, {UUID(int=1): (1, source()), UUID(int=2): (2, source())})
    selected = next(item for item in result.aliases if item.logical_alias == alias)
    assert selected.strategy == "weighted-rendezvous-v1"
    assert len(selected.eligible_shard_ids) == 2
    shards = [item for item in result.shards if item.shard_id in selected.eligible_shard_ids]
    assert {item.weight for item in shards} == {1, 3}
    assert shards[0].quota_pool_ids == shards[1].quota_pool_ids
    assert result.account_definitions == base.account_definitions
    assert result.profiles == base.profiles
    assert result.policy_catalog_digest == base.digest
    assert result.digest != base.digest
    assert base.aliases[0].eligible_shard_ids != selected.eligible_shard_ids


def test_unresolved_or_stale_source_choice_is_not_silently_replaced():
    from shared.model_access.source_catalog import compile_source_catalog

    base = base_catalog()
    choices = ModelSourceSelection.model_validate(
        {
            "aliases": [
                {
                    "logical_alias": base.aliases[0].logical_alias,
                    "sources": [{"source_id": str(UUID(int=1)), "revision": 2}],
                }
            ]
        }
    )
    for sources in [{}, {UUID(int=1): (1, source())}]:
        with pytest.raises(ContractError):
            compile_source_catalog(base, choices, sources)


@pytest.mark.parametrize("mutation", ["digest", "budget", "pool", "credential", "revision"])
def test_derived_catalog_cannot_borrow_authority_from_a_different_policy(mutation):
    from shared.model_access.source_catalog import compile_source_catalog

    base = base_catalog()
    choices = ModelSourceSelection.model_validate(
        {
            "aliases": [
                {
                    "logical_alias": base.aliases[0].logical_alias,
                    "sources": [{"source_id": str(UUID(int=1)), "revision": 1}],
                }
            ]
        }
    )
    result = compile_source_catalog(base, choices, {UUID(int=1): (1, source())})
    payload = result.model_dump(mode="json")
    if mutation == "digest":
        payload["policy_catalog_digest"] = "sha256:" + "1" * 64
    elif mutation == "budget":
        payload["profiles"][0]["limits"]["max_requests_per_window"] += 1
    elif mutation == "pool":
        next(p for p in payload["quota_pools"] if p["quota_pool_id"] == base.quota_pools[0].quota_pool_id)["limit"] += 1
    elif mutation == "credential":
        shard = next(s for s in payload["shards"] if s["credential_ref"]["reference"].startswith("source:"))
        shard["credential_ref"]["reference"] = f"source:{UUID(int=2)}:1"
    else:
        binding = next(b for b in payload["source_bindings"] if b["source_id"])
        binding["credential_revision"] = 2
    with pytest.raises(ContractError):
        seal_catalog(payload)


def test_cloud_sources_cannot_multiply_capacity_by_renaming_quota_identity():
    from shared.model_access.source_catalog import compile_source_catalog

    base = base_catalog()
    choices = ModelSourceSelection.model_validate(
        {
            "aliases": [
                {
                    "logical_alias": base.aliases[0].logical_alias,
                    "sources": [
                        {"source_id": str(UUID(int=1)), "revision": 1},
                        {"source_id": str(UUID(int=2)), "revision": 1},
                    ],
                }
            ]
        }
    )
    result = compile_source_catalog(
        base,
        choices,
        {
            UUID(int=1): (1, source()),
            UUID(int=2): (1, source().model_copy(update={"quota_identity": "renamed:capacity"})),
        },
    )
    shards = [s for s in result.shards if s.shard_id in result.aliases[0].eligible_shard_ids]
    assert shards[0].quota_pool_ids == shards[1].quota_pool_ids


def test_source_keeps_incumbent_cloud_quota_constraints():
    from shared.model_access.source_catalog import compile_source_catalog

    base = base_catalog()
    old = base.shards[0]
    project = old.model_project_ref.reference.removeprefix("project:")
    config = source().model_copy(
        update={
            "project": project,
            "principal": f"model-invoke@{project}.iam.gserviceaccount.com",
            "region": old.region,
            "model": old.provider_model,
        }
    )
    selection = ModelSourceSelection.model_validate(
        {
            "aliases": [
                {
                    "logical_alias": base.aliases[0].logical_alias,
                    "sources": [{"source_id": str(UUID(int=1)), "revision": 1}],
                }
            ]
        }
    )
    result = compile_source_catalog(base, selection, {UUID(int=1): (1, config)})
    chosen = next(s for s in result.shards if s.shard_id == result.aliases[0].eligible_shard_ids[0])
    assert set(old.quota_pool_ids).issubset(chosen.quota_pool_ids)
