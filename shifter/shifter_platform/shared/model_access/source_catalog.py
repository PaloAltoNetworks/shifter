"""Compile authorized source choices into the incumbent versioned catalog."""

from collections.abc import Mapping
from hashlib import sha256
from typing import Any
from uuid import UUID

from shared.model_access import ContractError, ModelAccessCatalog, seal_catalog
from shared.model_access.catalog_v3 import ModelAccessCatalogV3
from shared.model_access.sources import (
    AliasSourceSelection,
    ModelSourceConfiguration,
    ModelSourceSelection,
    SourceChoice,
)


def compile_source_catalog(
    base: ModelAccessCatalog,
    selection: ModelSourceSelection,
    sources: Mapping[UUID, tuple[int, ModelSourceConfiguration]],
) -> ModelAccessCatalog:
    """Preserve limits, accounts and sharing; only explicit aliases gain choices."""
    if not selection.aliases:
        return base
    if not isinstance(base, ModelAccessCatalogV3):
        raise ContractError("source.account_contract_unavailable")
    if base.contract_version != "model-access-policy/v3":
        raise ContractError("source.base_policy_required")
    payload = base.model_dump(mode="json")
    payload["policy_catalog"] = base.model_dump(mode="json")
    payload["contract_version"] = "model-access-policy/v4"
    payload["policy_catalog_digest"] = getattr(base, "policy_catalog_digest", None) or base.digest
    payload["source_bindings"] = payload.get(
        "source_bindings",
        [
            {
                "shard_id": item.shard_id,
                "source_id": None,
                "source_revision": 1,
                "credential_revision": 1,
                "price_schedule_id": None,
            }
            for item in base.shards
        ],
    )
    aliases = {item["logical_alias"]: item for item in payload["aliases"]}
    for selected in selection.aliases:
        alias = aliases.get(selected.logical_alias)
        if alias is None:
            raise ContractError("source.alias_unavailable")
        _select_alias_sources(payload, alias, selected, sources)
    return seal_catalog(payload)


def _select_alias_sources(
    payload: dict[str, Any],
    alias: dict[str, Any],
    selected: AliasSourceSelection,
    sources: Mapping[UUID, tuple[int, ModelSourceConfiguration]],
) -> None:
    """Apply immutable authorized revisions to one existing logical alias."""
    candidates = []
    for choice in selected.sources:
        entry = sources.get(choice.source_id)
        if entry is None or entry[0] != choice.revision:
            raise ContractError("source.revision_conflict")
        config = entry[1]
        candidates.append(_append_source(payload, alias, choice, config))
        if config.provider == "openrouter-v1":
            _remove_token_count(payload, alias["profile_id"])
    alias["eligible_shard_ids"] = candidates
    alias["strategy"] = "weighted-rendezvous-v1" if len(candidates) > 1 else "fixed-v1"
    # The inherited field validates protocol/currency; v4 settles using the
    # chosen shard's own immutable schedule, not this compatibility field.
    alias["price_schedule_id"] = f"price-{candidates[0]}"


def _remove_token_count(payload: dict[str, Any], profile_id: str) -> None:
    """Remove unsupported token counting from profiles using routed providers."""
    for profile in payload["profiles"]:
        if profile["profile_id"] == profile_id:
            profile["capabilities"] = [cap for cap in profile["capabilities"] if cap != "token-count"]


def _append_source(
    payload: dict[str, Any], alias: dict[str, Any], choice: SourceChoice, config: ModelSourceConfiguration
) -> str:
    """Append a source shard, its physical quota, immutable price and binding."""
    target = config.target(choice.source_id, choice.revision)
    shard_id = f"{target.shard_id}-{sha256(alias['logical_alias'].encode()).hexdigest()[:8]}"
    # Renaming or duplicating a source cannot create another physical quota.
    quota_identity = (config.provider, config.capacity_identity, "input_tokens", "tokens/minute")
    quota = next(
        (
            item
            for item in payload["quota_pools"]
            if (item["provider_adapter_id"], item["provider_quota_identity"], item["dimension"], item["unit"])
            == quota_identity
        ),
        None,
    )
    if quota is None:
        quota = {
            "quota_pool_id": "source-quota-" + sha256("|".join(quota_identity).encode()).hexdigest()[:32],
            "provider_adapter_id": config.provider,
            "provider_quota_identity": config.capacity_identity,
            "dimension": "input_tokens",
            "unit": "tokens/minute",
            "limit": config.tokens_per_minute,
        }
        payload["quota_pools"].append(quota)
    else:
        quota["limit"] = min(quota["limit"], config.tokens_per_minute)
    original = next(item for item in payload["shards"] if item["shard_id"] == alias["eligible_shard_ids"][0])
    payload["shards"].append(
        {
            **original,
            "shard_id": shard_id,
            "provider_adapter_id": config.provider,
            "model_project_ref": {"owner": "engine", "reference": config.project or f"source:{choice.source_id}"},
            "model_account_ref": {"owner": "engine", "reference": config.capacity_identity},
            "credential_ref": {"owner": "broker", "reference": target.credential_reference},
            "region": config.region,
            "provider_model": config.model,
            "provider_model_version": f"source-v{choice.revision}",
            "capabilities": ["messages"] if config.provider == "openrouter-v1" else ["messages", "token-count"],
            "billing_components": ["input_tokens", "output_tokens", "request"],
            "quota_pool_ids": sorted({quota["quota_pool_id"], *_incumbent_quotas(payload, config)}),
            "weight": choice.weight,
            "enabled": True,
        }
    )
    price_id = f"price-{shard_id}"
    payload["price_schedules"].append(
        {
            "price_schedule_id": price_id,
            "currency": config.currency.value,
            "valid_until": config.price_valid_until.isoformat(),
            "prices": [
                {
                    "component": "input_tokens",
                    "unit_denominator": 1_000_000,
                    "price_micro_units": config.input_price_per_million,
                },
                {
                    "component": "output_tokens",
                    "unit_denominator": 1_000_000,
                    "price_micro_units": config.output_price_per_million,
                },
                {"component": "request", "unit_denominator": 1, "price_micro_units": 0},
            ],
        }
    )
    payload["source_bindings"].append(
        {
            "shard_id": shard_id,
            "source_id": str(choice.source_id),
            "source_revision": choice.revision,
            "credential_revision": choice.revision,
            "price_schedule_id": price_id,
        }
    )
    return shard_id


def _incumbent_quotas(payload: dict[str, Any], config: ModelSourceConfiguration) -> set[str]:
    """Keep baseline quota identities when a tenant selects the same cloud source.

    The account/region ceiling also applies, but it must not hide reservations
    or observed usage under a legacy model-specific identity.
    """
    base = payload["policy_catalog"]
    pools = {
        pool["quota_pool_id"]
        for pool in base["quota_pools"]
        if pool["provider_adapter_id"] == config.provider
        and (
            pool["provider_quota_identity"] == config.capacity_identity
            or pool["provider_quota_identity"].startswith(config.capacity_identity + "/")
        )
    }
    if config.provider == "vertex-v1":
        for shard in base["shards"]:
            if (
                shard["provider_adapter_id"] == config.provider
                and shard["region"] == config.region
                and shard["provider_model"] == config.model
                and shard["model_project_ref"]["reference"] in {config.project, f"project:{config.project}"}
            ):
                pools.update(shard["quota_pool_ids"])
    return pools
