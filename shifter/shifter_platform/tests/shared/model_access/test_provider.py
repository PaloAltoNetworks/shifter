"""Provider adapters expose closed capabilities and safe cancellation truth."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.model_access import (
    BillingComponent,
    CancellationDisposition,
    CancellationResult,
    ContractError,
    ProviderAdapterRegistry,
    ProviderCapabilities,
    load_catalog_json,
)

EXAMPLE = Path(__file__).parents[5] / "docs/architecture/model-access/example-policy.v1.json"


class _Adapter:
    def __init__(self, **capability_overrides):
        self._capability_overrides = capability_overrides

    def capabilities(self):
        values = {
            "adapter_id": "vertex-v1",
            "protocols": ("anthropic-messages/2023-06-01",),
            "models": ("publishers/anthropic/models/claude-sonnet",),
            "capabilities": ("messages", "token-count"),
            "billing_components": (BillingComponent.INPUT_TOKENS,),
            "trustworthy_usage_components": (BillingComponent.INPUT_TOKENS,),
            "streaming": True,
            "token_counting": True,
            "cancellation": False,
            "completion_horizon_seconds": 3600,
        }
        values.update(self._capability_overrides)
        return ProviderCapabilities(**values)


def test_registry_selects_by_shard_adapter_instead_of_compute_cloud():
    shard = load_catalog_json(EXAMPLE.read_text(encoding="utf-8")).shards[0]
    registry = ProviderAdapterRegistry({"vertex-v1": lambda _: _Adapter()})
    assert registry.build(shard).capabilities().adapter_id == "vertex-v1"


def test_unknown_adapter_fails_before_transport():
    shard = load_catalog_json(EXAMPLE.read_text(encoding="utf-8")).shards[0]
    registry = ProviderAdapterRegistry({})
    with pytest.raises(ContractError) as exc:
        registry.build(shard)
    assert exc.value.code == "provider.unknown_adapter"


@pytest.mark.parametrize(
    "adapter_overrides,expected_path",
    [
        ({"adapter_id": "other-v1"}, "provider_adapter_id"),
        ({"protocols": ("other-protocol/v1",)}, "<root>"),
        ({"models": ("other-model",)}, "<root>"),
        ({"capabilities": ("messages",)}, "capabilities"),
        (
            {
                "billing_components": (BillingComponent.OUTPUT_TOKENS,),
                "trustworthy_usage_components": (BillingComponent.OUTPUT_TOKENS,),
            },
            "billing_components",
        ),
    ],
)
def test_registry_rejects_every_shard_capability_mismatch(adapter_overrides, expected_path):
    shard = load_catalog_json(EXAMPLE.read_text(encoding="utf-8")).shards[0]
    registry = ProviderAdapterRegistry({"vertex-v1": lambda _: _Adapter(**adapter_overrides)})
    with pytest.raises(ContractError) as exc:
        registry.build(shard)
    assert exc.value.code == "provider.capability_mismatch"
    assert exc.value.path == expected_path


@pytest.mark.parametrize(
    "disposition,may_release",
    [
        (CancellationDisposition.CONFIRMED, True),
        (CancellationDisposition.REQUESTED_UNCONFIRMED, False),
        (CancellationDisposition.UNSUPPORTED, False),
        (CancellationDisposition.UNKNOWN, False),
    ],
)
def test_only_confirmed_cancellation_may_release_reservation(disposition, may_release):
    assert CancellationResult(disposition=disposition).may_release_reservation is may_release


def test_provider_capabilities_reject_duplicate_and_unbounded_sets():
    values = {
        "adapter_id": "vertex-v1",
        "protocols": ("messages/v1",),
        "models": ("model-v1",),
        "capabilities": ("messages",),
        "billing_components": (BillingComponent.INPUT_TOKENS,),
        "trustworthy_usage_components": (BillingComponent.INPUT_TOKENS,),
        "streaming": True,
        "token_counting": True,
        "cancellation": False,
        "completion_horizon_seconds": 3600,
    }
    with pytest.raises(ValidationError):
        ProviderCapabilities(**{**values, "protocols": ("messages/v1", "messages/v1")})
    with pytest.raises(ValidationError):
        ProviderCapabilities(**{**values, "models": tuple(f"model-{index}" for index in range(257))})
