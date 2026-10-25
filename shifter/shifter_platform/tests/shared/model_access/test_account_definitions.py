"""Versioned account definitions resolve opaque spend/rate/concurrency refs (M04)."""

from __future__ import annotations

import json

import pytest
from test_provider_pools import v2_payload

from shared.model_access import (
    AccountDimension,
    ContractError,
    load_catalog_json,
    resolve_request_accounts,
    seal_catalog,
    validate_catalog,
)


def _account_definitions():
    return [
        {
            "account_ref": "deployment-spend",
            "dimension": "spend",
            "unit": "micro_units",
            "currency": "USD",
            "ceiling": 5_000_000,
            "window": {"kind": "utc_rolling", "period_seconds": 2_592_000},
            "definition_revision": 1,
            "authority_source": "deployment_catalog",
        },
        {
            "account_ref": "deployment-rate",
            "dimension": "rate",
            "unit": "requests",
            "currency": None,
            "ceiling": 10_000,
            "window": {"kind": "utc_rolling", "period_seconds": 60},
            "definition_revision": 1,
            "authority_source": "deployment_catalog",
        },
        {
            "account_ref": "deployment-concurrency",
            "dimension": "concurrency",
            "unit": "requests",
            "currency": None,
            "ceiling": 8,
            "window": {"kind": "lifetime", "period_seconds": None},
            "definition_revision": 1,
            "authority_source": "deployment_catalog",
        },
    ]


def v3_payload():
    payload = v2_payload()
    payload.update(
        contract_version="model-access-policy/v3",
        account_definitions=_account_definitions(),
        sharing_pools=[
            {
                "sharing_pool_id": "cohort-pool",
                "routing_revision": 1,
                "spend_account_refs": ["deployment-spend"],
                "rate_account_refs": ["deployment-rate"],
                "concurrency_account_refs": ["deployment-concurrency"],
            }
        ],
    )
    return payload


def test_v3_roundtrips_and_pins_account_definitions():
    catalog = seal_catalog(v3_payload())
    assert catalog.contract_version == "model-access-policy/v3"
    spend = next(d for d in catalog.account_definitions if d.dimension is AccountDimension.SPEND)
    assert spend.ceiling == 5_000_000
    assert spend.currency == "USD"
    assert load_catalog_json(catalog.model_dump_json()) == catalog
    changed = catalog.model_dump(mode="json")
    changed["account_definitions"][0]["ceiling"] = 1
    with pytest.raises(ContractError, match=r"contract\.digest_mismatch"):
        validate_catalog(changed)


def test_unresolved_account_reference_denies_publication():
    payload = v3_payload()
    payload["sharing_pools"][0]["spend_account_refs"] = ["missing-account"]
    with pytest.raises(ContractError, match=r"contract\.validation"):
        seal_catalog(payload)


def test_account_dimension_mismatch_denies_publication():
    payload = v3_payload()
    # Point the spend facet at the rate-dimension account.
    payload["sharing_pools"][0]["spend_account_refs"] = ["deployment-rate"]
    with pytest.raises(ContractError, match=r"contract\.validation"):
        seal_catalog(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        # spend account without currency
        {"index": 0, "field": "currency", "value": None},
        # non-spend account carrying a currency
        {"index": 1, "field": "currency", "value": "USD"},
        # rolling window without a period
        {"index": 0, "field": "window", "value": {"kind": "utc_rolling", "period_seconds": None}},
        # lifetime window carrying a period
        {"index": 2, "field": "window", "value": {"kind": "lifetime", "period_seconds": 60}},
    ],
)
def test_invalid_account_definition_denies_publication(mutation):
    payload = v3_payload()
    payload["account_definitions"][mutation["index"]][mutation["field"]] = mutation["value"]
    with pytest.raises(ContractError, match=r"contract\.validation"):
        seal_catalog(payload)


def test_duplicate_account_reference_denies_publication():
    payload = v3_payload()
    payload["account_definitions"].append(dict(payload["account_definitions"][0]))
    with pytest.raises(ContractError, match=r"contract\.validation"):
        seal_catalog(payload)


def test_v1_and_v2_reject_account_definitions_leak():
    v1 = v2_payload()
    v1["contract_version"] = "model-access-policy/v1"
    v1.pop("provider_pools", None)
    v1["account_definitions"] = _account_definitions()
    with pytest.raises(ContractError, match=r"contract\.validation"):
        seal_catalog(v1)
    v2 = v2_payload()
    v2["account_definitions"] = _account_definitions()
    with pytest.raises(ContractError, match=r"contract\.validation"):
        seal_catalog(v2)


def test_resolve_request_accounts_returns_definitions_by_dimension():
    catalog = seal_catalog(v3_payload())
    resolved = resolve_request_accounts(
        catalog=catalog,
        spend_account_refs=("deployment-spend",),
        rate_account_refs=("deployment-rate",),
        concurrency_account_refs=("deployment-concurrency",),
    )
    assert {d.account_ref for d in resolved.spend} == {"deployment-spend"}
    assert resolved.spend[0].dimension is AccountDimension.SPEND
    assert {d.account_ref for d in resolved.rate} == {"deployment-rate"}
    assert {d.account_ref for d in resolved.concurrency} == {"deployment-concurrency"}


def test_resolve_request_accounts_deduplicates_overlapping_selectors():
    catalog = seal_catalog(v3_payload())
    resolved = resolve_request_accounts(
        catalog=catalog,
        spend_account_refs=("deployment-spend", "deployment-spend"),
        rate_account_refs=(),
        concurrency_account_refs=(),
    )
    assert len(resolved.spend) == 1


def test_resolve_request_accounts_fails_closed_on_unknown_ref():
    catalog = seal_catalog(v3_payload())
    with pytest.raises(ContractError, match=r"contract\.account_unresolved"):
        resolve_request_accounts(
            catalog=catalog,
            spend_account_refs=("ghost",),
            rate_account_refs=(),
            concurrency_account_refs=(),
        )


def test_v3_installation_schema_matches_generated_source():
    from pathlib import Path

    from shared.model_access import model_access_catalog_schema

    path = Path(__file__).parents[4] / "installation/published_contract/model-access-policy.v3.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == model_access_catalog_schema("v3")
