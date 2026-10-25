"""Persistence invariants for the M04 request-accounting and lease records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from engine.models import (
    ModelAllocation,
    ModelBudgetAccount,
    ModelBudgetPosting,
    ModelDispatchLease,
    ModelReconciliationObligation,
    ModelRequestReservation,
)

pytestmark = pytest.mark.django_db

_LIFETIME_START = datetime(1970, 1, 1, tzinfo=UTC)
_LIFETIME_END = datetime(9999, 12, 31, tzinfo=UTC)


def _allocation() -> ModelAllocation:
    return ModelAllocation.objects.create(
        deployment_id=uuid4(),
        request_id=uuid4(),
        operation_id=uuid4(),
        range_id=uuid4(),
        draw_key=uuid4(),
        workload_role="participant",
        intent_digest="sha256:" + "a" * 64,
        policy_digest="sha256:" + "b" * 64,
        alias_shards={},
        snapshot={},
        deadline=datetime.now(UTC) + timedelta(hours=1),
    )


def _account(**overrides) -> ModelBudgetAccount:
    values = {
        "deployment_id": uuid4(),
        "account_ref": "deployment-spend",
        "dimension": "spend",
        "unit": "micro_units",
        "currency": "USD",
        "window_start": _LIFETIME_START,
        "window_end": _LIFETIME_END,
        "limit": 5_000_000,
        "definition_revision": 1,
    }
    values.update(overrides)
    return ModelBudgetAccount.objects.create(**values)


def _reservation(allocation, **overrides) -> ModelRequestReservation:
    values = {
        "request_uuid": uuid4(),
        "allocation": allocation,
        "operation_id": allocation.operation_id,
        "grant_epoch": 1,
        "logical_alias": "coding-main",
        "shard": {"shard_id": "vertex-primary"},
        "reservation_vector": {},
        "canonical_request_cost": 100,
    }
    values.update(overrides)
    return ModelRequestReservation.objects.create(**values)


def test_budget_account_is_unique_per_window():
    deployment = uuid4()
    _account(deployment_id=deployment, window_start=_LIFETIME_START, window_end=_LIFETIME_END)
    with pytest.raises(IntegrityError):
        _account(deployment_id=deployment, window_start=_LIFETIME_START, window_end=_LIFETIME_END)


def test_distinct_windows_for_same_account_coexist():
    deployment = uuid4()
    _account(deployment_id=deployment, window_start=_LIFETIME_START, window_end=_LIFETIME_END)
    later = _LIFETIME_START + timedelta(days=30)
    _account(deployment_id=deployment, window_start=later, window_end=later + timedelta(days=30))
    assert ModelBudgetAccount.objects.filter(deployment_id=deployment).count() == 2


def test_budget_reduction_below_committed_value_is_allowed():
    account = _account(limit=5_000_000)
    account.spent = 4_000_000
    account.reserved = 2_000_000
    account.save(update_fields=["spent", "reserved"])
    # A budget cut can legitimately push an account over limit; no DB constraint blocks it.
    account.limit = 1_000_000
    account.save(update_fields=["limit"])
    account.refresh_from_db()
    assert account.limit == 1_000_000
    assert account.spent + account.reserved == 6_000_000


def test_one_posting_per_request_and_account():
    allocation = _allocation()
    account = _account()
    reservation = _reservation(allocation)
    ModelBudgetPosting.objects.create(reservation=reservation, account=account, held=100)
    with pytest.raises(IntegrityError):
        ModelBudgetPosting.objects.create(reservation=reservation, account=account, held=200)


def test_scoped_retry_key_is_unique_within_grant_and_operation():
    allocation = _allocation()
    key = "sha256:" + "c" * 64
    _reservation(allocation, caller_key_hmac=key, key_version="k1")
    with pytest.raises(IntegrityError):
        _reservation(allocation, caller_key_hmac=key, key_version="k1")


def test_absent_retry_key_permits_independent_requests():
    allocation = _allocation()
    _reservation(allocation)  # no caller key -> empty sentinel, excluded from uniqueness
    _reservation(allocation)
    assert ModelRequestReservation.objects.filter(allocation=allocation).count() == 2


def test_new_grant_epoch_does_not_collide_with_prior_key():
    allocation = _allocation()
    key = "sha256:" + "d" * 64
    _reservation(allocation, grant_epoch=1, caller_key_hmac=key)
    # A re-admitted epoch reuses the key without colliding with the fenced prior epoch.
    _reservation(allocation, grant_epoch=2, caller_key_hmac=key)
    assert ModelRequestReservation.objects.filter(allocation=allocation, caller_key_hmac=key).count() == 2


def test_single_dispatch_lease_per_reservation():
    allocation = _allocation()
    reservation = _reservation(allocation)
    ModelDispatchLease.objects.create(
        reservation=reservation,
        dispatch_token="t" * 32,
        dispatch_deadline=datetime.now(UTC) + timedelta(seconds=5),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        ModelDispatchLease.objects.create(
            reservation=reservation,
            dispatch_token="u" * 32,
            dispatch_deadline=datetime.now(UTC) + timedelta(seconds=5),
        )


def test_one_reconciliation_obligation_per_reservation():
    allocation = _allocation()
    reservation = _reservation(allocation)
    ModelReconciliationObligation.objects.create(
        reservation=reservation,
        allocation=allocation,
        next_attempt_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        ModelReconciliationObligation.objects.create(
            reservation=reservation,
            allocation=allocation,
            next_attempt_at=datetime.now(UTC) + timedelta(minutes=5),
        )
