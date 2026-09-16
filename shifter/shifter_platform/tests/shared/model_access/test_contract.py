"""Closed model-access policy, sharing, and provider contracts (PLAT-202)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.model_access import (
    AccessLimits,
    AllocationStrategy,
    BillingComponent,
    ContractError,
    ModelProfile,
    ScenarioNeed,
    SelectorKind,
    SharingSelector,
    canonical_bytes,
    compute_digest,
    intersect_profile,
    load_catalog_json,
    model_access_catalog_schema,
    seal_catalog,
    seal_sharing_binding,
    validate_catalog,
)


def _limits(**overrides):
    values = {
        "max_request_seconds": 120,
        "max_request_bytes": 1_000_000,
        "max_input_tokens": 8_000,
        "max_output_tokens": 2_000,
        "max_requests_per_window": 60,
        "request_window_seconds": 60,
        "max_spend_micro_units": 5_000_000,
        "currency": "USD",
        "max_concurrent_requests": 2,
    }
    values.update(overrides)
    return AccessLimits.model_validate(values)


def _catalog_payload():
    payload = {
        "contract_version": "model-access-policy/v1",
        "deployment_id": "11111111-1111-4111-8111-111111111111",
        "enabled": False,
        "profiles": [
            {
                "profile_id": "coding",
                "capabilities": ["messages", "token-count"],
                "allowed_strategies": ["fixed-v1", "weighted-rendezvous-v1"],
                "data_regions": ["europe-west4"],
                "limits": _limits().model_dump(mode="json"),
            }
        ],
        "quota_pools": [
            {
                "quota_pool_id": "vertex-tokens-eu",
                "provider_adapter_id": "vertex-v1",
                "provider_quota_identity": "project:models-a/region:europe-west4/model:claude",
                "dimension": "input_tokens",
                "unit": "tokens/minute",
                "limit": 1000000,
            }
        ],
        "price_schedules": [
            {
                "price_schedule_id": "vertex-2026-09",
                "currency": "USD",
                "valid_until": "2026-10-01T00:00:00Z",
                "prices": [
                    {
                        "component": "input_tokens",
                        "unit_denominator": 1000000,
                        "price_micro_units": 3000000,
                    }
                ],
            }
        ],
        "shards": [
            {
                "shard_id": "vertex-primary",
                "provider_adapter_id": "vertex-v1",
                "compute_target_ref": {"owner": "installation", "reference": "gcp:gce-primary"},
                "model_project_ref": {"owner": "deployment", "reference": "project:models-a"},
                "model_account_ref": {"owner": "deployment", "reference": "billing:models-a"},
                "dynamic_secret_project_ref": {"owner": "deployment", "reference": "project:secrets-a"},
                "broker_workload_identity_ref": {"owner": "deployment", "reference": "gsa:model-broker"},
                "credential_ref": {"owner": "broker", "reference": "impersonate:gsa/model-invoke"},
                "region": "europe-west4",
                "provider_model": "publishers/anthropic/models/claude-sonnet",
                "provider_model_version": "20260901",
                "protocol": "anthropic-messages/2023-06-01",
                "capabilities": ["messages", "token-count"],
                "billing_components": ["input_tokens"],
                "quota_pool_ids": ["vertex-tokens-eu"],
                "weight": 1,
                "enabled": True,
            }
        ],
        "aliases": [
            {
                "logical_alias": "coding-main",
                "profile_id": "coding",
                "strategy": "fixed-v1",
                "affinity": "per_range",
                "eligible_shard_ids": ["vertex-primary"],
                "price_schedule_id": "vertex-2026-09",
            }
        ],
        "sharing_pools": [],
        "sharing_bindings": [],
    }
    payload["digest"] = compute_digest(payload)
    return payload


def test_complete_catalog_round_trips_and_has_stable_canonical_bytes():
    payload = _catalog_payload()
    catalog = validate_catalog(payload)
    raw = json.dumps(payload, ensure_ascii=False)

    assert load_catalog_json(raw) == catalog
    assert canonical_bytes(catalog) == canonical_bytes(validate_catalog(json.loads(raw)))
    assert catalog.digest == compute_digest(catalog)


def test_canonical_json_matches_published_utf8_vector():
    vector_path = Path(__file__).parents[5] / "docs/architecture/model-access/canonical-json-v1-vector.json"
    vector = json.loads(vector_path.read_text(encoding="utf-8"))
    assert canonical_bytes(vector["input"]).decode("utf-8") == vector["canonical_utf8"]
    assert compute_digest(vector["input"]) == vector["digest"]


def test_sealing_normalizes_orderless_sets_before_digesting():
    payload = _catalog_payload()
    payload.pop("digest")
    payload["profiles"][0]["capabilities"].reverse()
    sealed = seal_catalog(payload)
    assert sealed.profiles[0].capabilities == ("messages", "token-count")
    assert sealed.digest == _catalog_payload()["digest"]


def test_raw_json_rejects_duplicate_members_before_mapping_construction():
    raw = '{"contract_version":"model-access-policy/v1","contract_version":"model-access-policy/v2"}'
    with pytest.raises(ContractError) as exc:
        load_catalog_json(raw)
    assert exc.value.code == "contract.duplicate_member"
    assert exc.value.path == "contract_version"
    assert "model-access-policy/v2" not in str(exc.value)


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda p: p.update({"contract_version": "model-access-policy/v2"}), "contract.validation"),
        (lambda p: p["profiles"][0].pop("limits"), "contract.validation"),
        (lambda p: p["profiles"][0]["limits"].update({"currency": "XYZ"}), "contract.validation"),
        (lambda p: p["shards"][0].update({"weight": 65}), "contract.validation"),
        (lambda p: p.update({"surprise": True}), "contract.validation"),
    ],
)
def test_catalog_fails_closed_on_unsupported_or_unsafe_input(mutate, code):
    payload = _catalog_payload()
    mutate(payload)
    payload["digest"] = compute_digest(payload)
    with pytest.raises(ContractError) as exc:
        validate_catalog(payload)
    assert exc.value.code == code


def test_digest_mismatch_is_bounded_and_does_not_echo_rejected_values():
    payload = _catalog_payload()
    payload["digest"] = "sha256:" + "f" * 64
    with pytest.raises(ContractError) as exc:
        validate_catalog(payload)
    assert exc.value.code == "contract.digest_mismatch"
    assert "vertex-primary" not in str(exc.value)


def test_duplicate_real_quota_identity_cannot_manufacture_headroom():
    payload = _catalog_payload()
    duplicate = dict(payload["quota_pools"][0])
    duplicate["quota_pool_id"] = "fake-second-pool"
    payload["quota_pools"].append(duplicate)
    payload["digest"] = compute_digest(payload)
    with pytest.raises(ContractError) as exc:
        validate_catalog(payload)
    assert exc.value.code == "contract.validation"


def test_profile_intersection_tightens_sets_and_every_ceiling():
    profile = ModelProfile(
        profile_id="coding",
        capabilities=("messages", "token-count"),
        allowed_strategies=(AllocationStrategy.FIXED_V1, AllocationStrategy.WEIGHTED_RENDEZVOUS_V1),
        data_regions=("europe-west4", "us-central1"),
        limits=_limits(),
    )
    need = ScenarioNeed(
        contract_version="model-access-scenario/v1",
        scenario_digest="sha256:" + "a" * 64,
        workload_role="participant",
        profile_id="coding",
        required=True,
        required_capabilities=("messages",),
        allowed_capabilities=("messages",),
        allowed_strategies=(AllocationStrategy.FIXED_V1,),
        data_regions=("europe-west4",),
        limits=_limits(max_request_seconds=30, max_concurrent_requests=1),
    )
    effective = intersect_profile(profile, need)
    assert effective.capabilities == ("messages",)
    assert effective.allowed_strategies == (AllocationStrategy.FIXED_V1,)
    assert effective.data_regions == ("europe-west4",)
    assert effective.limits.max_request_seconds == 30
    assert effective.limits.max_concurrent_requests == 1


def test_required_capability_outside_profile_is_rejected():
    profile = ModelProfile(
        profile_id="coding",
        capabilities=("messages",),
        allowed_strategies=(AllocationStrategy.FIXED_V1,),
        data_regions=("europe-west4",),
        limits=_limits(),
    )
    need = ScenarioNeed(
        contract_version="model-access-scenario/v1",
        scenario_digest="sha256:" + "a" * 64,
        workload_role="participant",
        profile_id="coding",
        required=True,
        required_capabilities=("tools",),
        allowed_capabilities=("messages", "tools"),
        allowed_strategies=(AllocationStrategy.FIXED_V1,),
        data_regions=("europe-west4",),
        limits=_limits(),
    )
    with pytest.raises(ContractError) as exc:
        intersect_profile(profile, need)
    assert exc.value.code == "policy.required_capability_unavailable"


def test_optional_need_can_resolve_to_visible_unavailability():
    profile = ModelProfile(
        profile_id="coding",
        capabilities=("messages",),
        allowed_strategies=(AllocationStrategy.FIXED_V1,),
        data_regions=("europe-west4",),
        limits=_limits(),
    )
    need = ScenarioNeed(
        contract_version="model-access-scenario/v1",
        scenario_digest="sha256:" + "a" * 64,
        workload_role="participant",
        profile_id="coding",
        required=False,
        required_capabilities=("tools",),
        allowed_capabilities=("tools",),
        allowed_strategies=(AllocationStrategy.FIXED_V1,),
        data_regions=("europe-west4",),
        limits=_limits(),
    )
    assert intersect_profile(profile, need) is None


def test_sharing_selectors_are_closed_bounded_and_non_recursive():
    selected = SharingSelector(kind=SelectorKind.SELECTED_RANGES, ids=("range-1", "range-2"))
    union = SharingSelector(kind=SelectorKind.NAMED_COLLECTION, members=(selected,))
    assert union.members == (selected,)
    with pytest.raises(ValidationError):
        SharingSelector(kind=SelectorKind.NAMED_COLLECTION, members=(union,))
    with pytest.raises(ValidationError):
        SharingSelector(kind=SelectorKind.SELECTED_RANGES, ids=("range-1", "range-1"))


def test_named_collection_members_have_canonical_set_semantics():
    without_spares = SharingSelector(kind=SelectorKind.CTF_EVENT, ids=("event-1",), include_spares=False)
    with_spares = SharingSelector(kind=SelectorKind.CTF_EVENT, ids=("event-1",), include_spares=True)
    forward = SharingSelector(kind=SelectorKind.NAMED_COLLECTION, members=(without_spares, with_spares))
    reverse = SharingSelector(kind=SelectorKind.NAMED_COLLECTION, members=(with_spares, without_spares))
    assert forward == reverse
    with pytest.raises(ValidationError):
        SharingSelector(kind=SelectorKind.NAMED_COLLECTION, members=(without_spares, without_spares))


def test_named_collection_enforces_aggregate_id_bound():
    half = SharingSelector(kind=SelectorKind.SELECTED_RANGES, ids=tuple(f"range-{i}" for i in range(500)))
    other_half = SharingSelector(kind=SelectorKind.USER, ids=tuple(f"user-{i}" for i in range(500)))
    at_limit = SharingSelector(kind=SelectorKind.NAMED_COLLECTION, members=(half, other_half))
    assert len(at_limit.members) == 2

    over = SharingSelector(kind=SelectorKind.USER, ids=tuple(f"user-{i}" for i in range(501)))
    with pytest.raises(ValidationError):
        SharingSelector(kind=SelectorKind.NAMED_COLLECTION, members=(half, over))


def test_include_spares_only_valid_for_ctf_selectors():
    for kind in (SelectorKind.CTF_EVENT, SelectorKind.CTF_COHORT, SelectorKind.CTF_TEAM):
        assert SharingSelector(kind=kind, ids=("x",), include_spares=True).include_spares is True
    for kind in (
        SelectorKind.SELECTED_RANGES,
        SelectorKind.USER,
        SelectorKind.AUTH_GROUP,
        SelectorKind.WORKSPACE,
        SelectorKind.ORGANIZATION,
    ):
        with pytest.raises(ValidationError):
            SharingSelector(kind=kind, ids=("x",), include_spares=True)


def test_shared_only_pool_and_all_ranges_binding_are_closed_and_digest_bound():
    payload = _catalog_payload()
    binding = {
        "contract_version": "model-access-sharing/v1",
        "sharing_binding_id": "deployment-shared",
        "deployment_id": payload["deployment_id"],
        "selector": {"kind": "all_ranges"},
        "membership_mode": "dynamic",
        "membership_revision": 1,
        "authorized_publisher_ref": {"owner": "deployment", "reference": "operator:platform"},
        "profile_id": None,
        "sharing_pool_id": "shared-budget",
        "facets": ["routing", "spend"],
        "priority": 100,
        "effective_from": "2026-09-01T00:00:00Z",
        "effective_until": "2026-10-01T00:00:00Z",
    }
    binding = seal_sharing_binding(binding).model_dump(mode="json")
    payload["sharing_pools"] = [
        {
            "sharing_pool_id": "shared-budget",
            "routing_revision": 1,
            "alias_affinities": [{"logical_alias": "coding-main", "affinity": "per_pool"}],
            "spend_account_refs": ["shared-budget-account", "range-budget-account"],
        }
    ]
    payload["sharing_bindings"] = [binding]
    payload.pop("digest")
    catalog = seal_catalog(payload)
    assert catalog.sharing_pools[0].spend_account_refs == ("range-budget-account", "shared-budget-account")
    assert catalog.sharing_bindings[0].selector.kind is SelectorKind.ALL_RANGES


def test_sharing_binding_definition_digest_mismatch_is_rejected():
    payload = _catalog_payload()
    payload["sharing_pools"] = [{"sharing_pool_id": "pool", "routing_revision": 1, "spend_account_refs": ["a"]}]
    payload["sharing_bindings"] = [
        {
            "contract_version": "model-access-sharing/v1",
            "sharing_binding_id": "binding",
            "deployment_id": payload["deployment_id"],
            "selector": {"kind": "all_ranges"},
            "membership_mode": "dynamic",
            "membership_revision": 1,
            "authorized_publisher_ref": {"owner": "deployment", "reference": "operator:platform"},
            "sharing_pool_id": "pool",
            "facets": ["spend"],
            "priority": 0,
            "effective_from": "2026-09-01T00:00:00Z",
            "effective_until": "2026-10-01T00:00:00Z",
            "definition_digest": "sha256:" + "f" * 64,
        }
    ]
    payload["digest"] = compute_digest(payload)
    with pytest.raises(ContractError) as exc:
        validate_catalog(payload)
    assert exc.value.path.endswith("definition_digest")


def test_provider_billing_component_is_closed():
    assert BillingComponent("input_tokens") is BillingComponent.INPUT_TOKENS
    with pytest.raises(ValueError):
        BillingComponent("mystery_fee")


def test_generated_schema_is_closed_and_versioned():
    schema = model_access_catalog_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["contract_version"]["const"] == "model-access-policy/v1"
