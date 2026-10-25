"""Behavioural tests for atomic request-budget reservation (M04)."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from engine.models import (
    ModelAllocation,
    ModelBudgetAccount,
    ModelBudgetPosting,
    ModelPendingGrant,
    ModelRequestReservation,
)
from engine.services import RequestIdempotency, reserve_request
from shared.model_access import ContractError, seal_catalog
from shared.model_access.core_models import AccessLimits, EffectiveProfile, OwnedReference
from shared.model_access.effective_policy import EffectivePolicy

pytestmark = pytest.mark.django_db

_FAR_FUTURE = "2027-10-01T00:00:00Z"


class _FailingAuditWriter:
    """An audit writer whose persistence always fails, exercising the strict path."""

    def write(self, event):
        raise RuntimeError("audit unavailable")


@contextlib.contextmanager
def failing_audit_writer():
    """Swap in a failing audit writer through the public port seam, then restore it.

    Using the port's own binding contract (not an internal mock) keeps this within
    the boundary-mock policy while still driving the strict fail-closed audit path.
    """
    from shared.audit.port import bind_audit_writer, get_audit_writer, reset_audit_writer

    original = get_audit_writer()
    reset_audit_writer()
    bind_audit_writer(_FailingAuditWriter())
    try:
        yield
    finally:
        reset_audit_writer()
        bind_audit_writer(original)


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


def seal_v3_catalog(deployment_id, *, valid_until=_FAR_FUTURE, spend_ceiling=5_000_000, spend_currency="USD"):
    payload = {
        "contract_version": "model-access-policy/v3",
        "deployment_id": str(deployment_id),
        "enabled": True,
        "profiles": [
            {
                "profile_id": "coding",
                "capabilities": ["messages"],
                "allowed_strategies": ["fixed-v1"],
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
                "limit": 1_000_000,
            }
        ],
        "price_schedules": [
            {
                "price_schedule_id": "vertex-price",
                "currency": "USD",
                "valid_until": valid_until,
                "prices": [
                    {"component": "input_tokens", "unit_denominator": 1_000_000, "price_micro_units": 3_000_000},
                    {"component": "output_tokens", "unit_denominator": 1_000_000, "price_micro_units": 15_000_000},
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
                "capabilities": ["messages"],
                "billing_components": ["input_tokens", "output_tokens"],
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
                "price_schedule_id": "vertex-price",
            }
        ],
        "provider_pools": [{"provider_pool_id": "classroom", "shard_ids": ["vertex-primary"]}],
        "account_definitions": [
            {
                "account_ref": "deployment-spend",
                "dimension": "spend",
                "unit": "micro_units",
                "currency": spend_currency,
                "ceiling": spend_ceiling,
                "window": {"kind": "lifetime", "period_seconds": None},
                "definition_revision": 1,
                "authority_source": "deployment_catalog",
            },
            {
                "account_ref": "deployment-rate",
                "dimension": "rate",
                "unit": "requests",
                "currency": None,
                "ceiling": 60,
                "window": {"kind": "utc_rolling", "period_seconds": 60},
                "definition_revision": 1,
                "authority_source": "deployment_catalog",
            },
            {
                "account_ref": "deployment-concurrency",
                "dimension": "concurrency",
                "unit": "requests",
                "currency": None,
                "ceiling": 2,
                "window": {"kind": "lifetime", "period_seconds": None},
                "definition_revision": 1,
                "authority_source": "deployment_catalog",
            },
        ],
        "sharing_pools": [
            {
                "sharing_pool_id": "cohort-pool",
                "routing_revision": 1,
                "spend_account_refs": ["deployment-spend"],
                "rate_account_refs": ["deployment-rate"],
                "concurrency_account_refs": ["deployment-concurrency"],
            }
        ],
        "sharing_bindings": [],
    }
    return seal_catalog(payload)


def _effective_policy(deployment_id, catalog_digest):
    return EffectivePolicy(
        deployment_id=deployment_id,
        catalog_digest=catalog_digest,
        evaluated_at=datetime.now(UTC),
        subject=OwnedReference(owner="management", reference="user:1"),
        effective_profile=EffectiveProfile(
            profile_id="coding",
            required=True,
            capabilities=("messages",),
            allowed_strategies=("fixed-v1",),
            data_regions=("europe-west4",),
            limits=_limits(),
        ),
        provider_pool_ref="classroom",
        capacity_account_refs=(),
        spend_account_refs=("deployment-spend",),
        rate_account_refs=("deployment-rate",),
        concurrency_account_refs=("deployment-concurrency",),
        alias_routings=(),
        contributions=(),
        conflicts=(),
        stale=False,
    )


def make_reservable_allocation(*, deployment_id=None, spend_ceiling=5_000_000, spend_currency="USD"):
    deployment_id = deployment_id or uuid4()
    catalog = seal_v3_catalog(deployment_id, spend_ceiling=spend_ceiling, spend_currency=spend_currency)
    effective = _effective_policy(deployment_id, catalog.digest)
    shard = next(item for item in catalog.shards if item.shard_id == "vertex-primary")
    allocation = ModelAllocation.objects.create(
        deployment_id=deployment_id,
        request_id=uuid4(),
        operation_id=uuid4(),
        range_id=uuid4(),
        draw_key=uuid4(),
        workload_role="participant",
        intent_digest="sha256:" + "a" * 64,
        policy_digest="sha256:" + "b" * 64,
        alias_shards={"coding-main": "vertex-primary"},
        snapshot={
            "catalog": catalog.model_dump(mode="json"),
            "effective_policy": effective.model_dump(mode="json"),
            "shards": {"coding-main": shard.model_dump(mode="json")},
        },
        deadline=datetime.now(UTC) + timedelta(hours=1),
    )
    ModelPendingGrant.objects.create(allocation=allocation, grant_epoch=1, state="active")
    return allocation


def _bound(units=1000):
    from shared.model_access import BillingBound
    from shared.model_access.provider import BillingAmount

    return BillingBound(amounts=(BillingAmount(component="input_tokens", units=units, maximum_charge_micro_units=0),))


def _reserve(allocation, **overrides):
    values = {
        "allocation_id": allocation.pk,
        "request_uuid": uuid4(),
        "logical_alias": "coding-main",
        "billing_bound": _bound(),
    }
    values.update(overrides)
    return reserve_request(**values)


def test_reserve_places_one_posting_per_account_and_holds():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    # ceil(1000 * 3_000_000 / 1_000_000) = 3000 micro-units.
    assert outcome.canonical_request_cost == 3000
    assert set(outcome.account_refs) == {"deployment-spend", "deployment-rate", "deployment-concurrency"}
    assert ModelBudgetPosting.objects.filter(reservation__request_uuid=outcome.request_uuid).count() == 3
    spend = ModelBudgetAccount.objects.get(account_ref="deployment-spend")
    assert spend.reserved == 3000
    rate = ModelBudgetAccount.objects.get(account_ref="deployment-rate")
    assert rate.requests == 1
    concurrency = ModelBudgetAccount.objects.get(account_ref="deployment-concurrency")
    assert concurrency.active_leases == 1


def test_reserve_denies_when_spend_would_exceed_ceiling():
    allocation = make_reservable_allocation(spend_ceiling=2000)
    with pytest.raises(ContractError, match=r"request\.budget_exceeded"):
        _reserve(allocation)
    assert not ModelRequestReservation.objects.exists()
    assert not ModelBudgetPosting.objects.exists()


def test_reserve_denies_when_concurrency_slots_exhausted():
    allocation = make_reservable_allocation()
    _reserve(allocation)
    _reserve(allocation)  # two concurrent leases == ceiling of 2
    with pytest.raises(ContractError, match=r"request\.budget_exceeded"):
        _reserve(allocation)


def test_reserve_rejects_expired_price():
    deployment = uuid4()
    catalog = seal_v3_catalog(deployment, valid_until="2020-01-01T00:00:00Z")
    effective = _effective_policy(deployment, catalog.digest)
    shard = next(item for item in catalog.shards if item.shard_id == "vertex-primary")
    allocation = ModelAllocation.objects.create(
        deployment_id=deployment,
        request_id=uuid4(),
        operation_id=uuid4(),
        range_id=uuid4(),
        draw_key=uuid4(),
        workload_role="participant",
        intent_digest="sha256:" + "a" * 64,
        policy_digest="sha256:" + "b" * 64,
        alias_shards={"coding-main": "vertex-primary"},
        snapshot={
            "catalog": catalog.model_dump(mode="json"),
            "effective_policy": effective.model_dump(mode="json"),
            "shards": {"coding-main": shard.model_dump(mode="json")},
        },
        deadline=datetime.now(UTC) + timedelta(hours=1),
    )
    ModelPendingGrant.objects.create(allocation=allocation, grant_epoch=1, state="active")
    with pytest.raises(ContractError, match=r"request\.price_expired"):
        _reserve(allocation)


def test_reserve_rejects_charge_above_per_request_grant_bound():
    allocation = make_reservable_allocation()
    # 2_000_000 units * 3 micro-units/unit = 6_000_000 > max_spend_micro_units (5_000_000).
    with pytest.raises(ContractError, match=r"request\.bound_exceeds_grant"):
        _reserve(allocation, billing_bound=_bound(units=2_000_000))


def test_reserve_denies_a_revoked_grant():
    allocation = make_reservable_allocation()
    grant = ModelPendingGrant.objects.get(allocation=allocation)
    grant.state = "revoked"
    grant.save(update_fields=["state"])
    with pytest.raises(ContractError, match=r"request\.revoked"):
        _reserve(allocation)


def test_reserve_denies_a_pending_grant():
    # A pending grant is a non-usable enrollment binding; only an issued (active)
    # capability authorizes a request. M04 never activates it.
    allocation = make_reservable_allocation()
    ModelPendingGrant.objects.filter(allocation=allocation).update(state="pending")
    with pytest.raises(ContractError, match=r"request\.grant_inactive"):
        _reserve(allocation)
    assert not ModelRequestReservation.objects.exists()


def test_reserve_denies_an_expired_allocation():
    allocation = make_reservable_allocation()
    allocation.deadline = timezone.now() - timedelta(seconds=1)
    allocation.save(update_fields=["deadline"])
    with pytest.raises(ContractError, match=r"request\.allocation_expired"):
        _reserve(allocation)


def test_repeated_key_same_intent_returns_completed_metadata():
    allocation = make_reservable_allocation()
    idem = RequestIdempotency(caller_key_hmac="sha256:" + "c" * 64, intent_fingerprint_hmac="sha256:" + "f" * 64)
    first = _reserve(allocation, idempotency=idem)
    # Settle the first so the duplicate resolves to completed metadata.
    ModelRequestReservation.objects.filter(request_uuid=first.request_uuid).update(state="settled")
    second = _reserve(allocation, idempotency=idem)
    assert second.request_uuid == first.request_uuid


def test_repeated_key_changed_intent_conflicts():
    allocation = make_reservable_allocation()
    key = "sha256:" + "c" * 64
    _reserve(
        allocation, idempotency=RequestIdempotency(caller_key_hmac=key, intent_fingerprint_hmac="sha256:" + "1" * 64)
    )
    with pytest.raises(ContractError, match=r"request\.intent_conflict"):
        _reserve(
            allocation,
            idempotency=RequestIdempotency(caller_key_hmac=key, intent_fingerprint_hmac="sha256:" + "2" * 64),
        )


def test_repeated_key_still_in_progress_conflicts():
    allocation = make_reservable_allocation()
    idem = RequestIdempotency(caller_key_hmac="sha256:" + "c" * 64, intent_fingerprint_hmac="sha256:" + "f" * 64)
    _reserve(allocation, idempotency=idem)
    with pytest.raises(ContractError, match=r"request\.in_progress_or_unknown"):
        _reserve(allocation, idempotency=idem)


def test_no_retry_key_permits_independent_invocations():
    allocation = make_reservable_allocation()
    first = _reserve(allocation)
    second = _reserve(allocation)
    assert first.request_uuid != second.request_uuid
    assert ModelRequestReservation.objects.count() == 2


def test_reserve_rejects_spend_account_currency_mismatch():
    # Spend account is EUR while the price schedule and grant limits are USD.
    allocation = make_reservable_allocation(spend_currency="EUR")
    with pytest.raises(ContractError, match=r"request\.currency_mismatch"):
        _reserve(allocation)
    assert not ModelRequestReservation.objects.exists()


def test_reserve_rejects_account_reused_with_changed_semantics():
    allocation = make_reservable_allocation()
    _reserve(allocation)  # creates the spend account row
    account = ModelBudgetAccount.objects.get(account_ref="deployment-spend")
    account.unit = "cents"  # a later catalog reuses the ref with a different unit
    account.save(update_fields=["unit"])
    with pytest.raises(ContractError, match=r"request\.account_semantics_changed"):
        _reserve(allocation)


def test_hmac_rotation_replays_across_key_versions():
    allocation = make_reservable_allocation()
    old_hmac = "sha256:" + "a" * 64
    new_hmac = "sha256:" + "b" * 64
    fingerprint = "sha256:" + "f" * 64
    first = _reserve(
        allocation,
        idempotency=RequestIdempotency(caller_key_hmac=old_hmac, key_version="k1", intent_fingerprint_hmac=fingerprint),
    )
    ModelRequestReservation.objects.filter(request_uuid=first.request_uuid).update(state="settled")
    # After key rotation the same raw key hashes to new_hmac; the caller passes the
    # prior-version digest too, so the retry resolves to the original, not a new request.
    second = _reserve(
        allocation,
        idempotency=RequestIdempotency(
            caller_key_hmac=new_hmac,
            prior_caller_key_hmacs=(old_hmac,),
            retained_key_versions=("k1",),
            key_version="k2",
            intent_fingerprint_hmac=fingerprint,
        ),
    )
    assert second.request_uuid == first.request_uuid
    assert ModelRequestReservation.objects.count() == 1


def test_strict_audit_failure_rolls_back_the_whole_reservation():
    # The pre-dispatch decision audit is fail-closed: if it cannot commit, the
    # reservation, postings and account holds must not persist either.
    allocation = make_reservable_allocation()
    with failing_audit_writer(), pytest.raises(RuntimeError):
        _reserve(allocation)
    assert not ModelRequestReservation.objects.exists()
    assert not ModelBudgetPosting.objects.exists()
    assert not ModelBudgetAccount.objects.filter(account_ref="deployment-spend", reserved__gt=0).exists()


def test_reserve_writes_a_body_free_decision_audit_row():
    from shared.models import AuditLog

    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    row = AuditLog.objects.get(entity_ref=str(outcome.request_uuid))
    assert row.action == "request_reserve"
    assert row.entity_type == "model_request"
    assert row.entity_id == ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid).pk
    # Body-free: no prompt/response/fingerprint content in the audit context.
    assert "prompt" not in row.context.lower()
    assert "sha256" not in row.context.lower()


def test_lowered_ceiling_blocks_new_work_but_keeps_committed():
    allocation = make_reservable_allocation()
    _reserve(allocation)  # reserves 3000 against a 5_000_000 ceiling
    spend = ModelBudgetAccount.objects.get(account_ref="deployment-spend")
    spend.limit = 100  # operator budget cut below the committed reserve
    spend.save(update_fields=["limit"])
    with pytest.raises(ContractError, match=r"request\.budget_exceeded"):
        _reserve(allocation)
    spend.refresh_from_db()
    assert spend.reserved == 3000  # committed value retained


def test_key_rotation_without_retained_key_cannot_create_a_second_invocation():
    allocation = make_reservable_allocation()
    first = _reserve(
        allocation,
        idempotency=RequestIdempotency(caller_key_hmac="a" * 64, key_version="v1", intent_fingerprint_hmac="b" * 64),
    )
    ModelRequestReservation.objects.filter(request_uuid=first.request_uuid).update(state="settled")
    with pytest.raises(ContractError, match=r"request\.retry_key_rotation_unavailable"):
        _reserve(
            allocation,
            idempotency=RequestIdempotency(
                caller_key_hmac="c" * 64, key_version="v2", intent_fingerprint_hmac="d" * 64
            ),
        )
    assert ModelRequestReservation.objects.count() == 1
