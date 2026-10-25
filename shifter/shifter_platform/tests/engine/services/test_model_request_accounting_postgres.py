"""Real-PostgreSQL contention and crash-boundary proof for request accounting (M04).

These tests exercise concurrent reservation, shared-account first-use, duplicate
settlement and concurrency-slot exhaustion across distinct connections with real
row locks. SQLite and mocked locks are not concurrency evidence (ADR-060), so the
whole module runs only on the Postgres lane.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from django.db import connection

from engine.models import ModelBudgetAccount, ModelRequestReservation
from engine.services import open_dispatch, reserve_request, settle_request
from shared.model_access import ContractError
from shared.model_access.provider import ProviderUsage, VerifiedUsage

from .test_model_request_accounting import _bound, make_reservable_allocation

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def _run_concurrently(functions):
    """Run callables on distinct connections, released to maximise contention."""
    barrier = threading.Barrier(len(functions))

    def _wrapped(func):
        def inner():
            barrier.wait()
            try:
                return func()
            finally:
                connection.close()

        return inner

    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        futures = [pool.submit(_wrapped(func)) for func in functions]
        return [future.result() for future in futures]


def _reserve_call(allocation, units=1000):
    def call():
        try:
            reserve_request(
                allocation_id=allocation.pk,
                request_uuid=uuid4(),
                logical_alias="coding-main",
                billing_bound=_bound(units),
            )
            return "ok"
        except ContractError as exc:
            return exc.code

    return call


def test_concurrent_last_unit_reservation_admits_exactly_one():
    deployment = uuid4()
    # Ceiling admits a single 3000-micro-unit charge; two distinct ranges share it.
    first = make_reservable_allocation(deployment_id=deployment, spend_ceiling=3000)
    second = make_reservable_allocation(deployment_id=deployment, spend_ceiling=3000)
    results = _run_concurrently([_reserve_call(first), _reserve_call(second)])
    assert sorted(results) == ["ok", "request.budget_exceeded"]
    account = ModelBudgetAccount.objects.get(deployment_id=deployment, account_ref="deployment-spend")
    assert account.reserved == 3000  # exactly one hold, no lost update or over-reserve


def test_concurrent_first_use_creates_one_account_and_sums_holds():
    deployment = uuid4()
    first = make_reservable_allocation(deployment_id=deployment, spend_ceiling=5_000_000)
    second = make_reservable_allocation(deployment_id=deployment, spend_ceiling=5_000_000)
    results = _run_concurrently([_reserve_call(first), _reserve_call(second)])
    assert results == ["ok", "ok"]
    accounts = ModelBudgetAccount.objects.filter(deployment_id=deployment, account_ref="deployment-spend")
    assert accounts.count() == 1  # concurrent first use serialised to one durable identity
    assert accounts.get().reserved == 6000  # both holds accrued, none lost


def test_concurrent_concurrency_slots_admit_only_the_ceiling():
    deployment = uuid4()
    # Concurrency ceiling is 2 in the shared catalog; three concurrent requests race.
    allocations = [make_reservable_allocation(deployment_id=deployment) for _ in range(3)]
    results = _run_concurrently([_reserve_call(allocation) for allocation in allocations])
    assert results.count("ok") == 2
    assert results.count("request.budget_exceeded") == 1
    account = ModelBudgetAccount.objects.get(deployment_id=deployment, account_ref="deployment-concurrency")
    assert account.active_leases == 2


def test_denied_reserve_rolls_back_every_account_hold():
    # Accounts lock in canonical order (concurrency, rate, then spend); pre-committing
    # spend to its ceiling makes the final account fail after the earlier holds are
    # placed, proving the whole reserve rolls back atomically at the crash boundary.
    deployment = uuid4()
    allocation = make_reservable_allocation(deployment_id=deployment, spend_ceiling=3000)
    reserve_request(
        allocation_id=allocation.pk,
        request_uuid=uuid4(),
        logical_alias="coding-main",
        billing_bound=_bound(1000),
    )
    concurrency_before = ModelBudgetAccount.objects.get(
        deployment_id=deployment, account_ref="deployment-concurrency"
    ).active_leases
    rate_before = ModelBudgetAccount.objects.get(deployment_id=deployment, account_ref="deployment-rate").requests
    with pytest.raises(ContractError, match=r"request\.budget_exceeded"):
        reserve_request(
            allocation_id=allocation.pk,
            request_uuid=uuid4(),
            logical_alias="coding-main",
            billing_bound=_bound(1000),
        )
    concurrency = ModelBudgetAccount.objects.get(deployment_id=deployment, account_ref="deployment-concurrency")
    rate = ModelBudgetAccount.objects.get(deployment_id=deployment, account_ref="deployment-rate")
    assert concurrency.active_leases == concurrency_before  # earlier holds rolled back
    assert rate.requests == rate_before
    assert ModelRequestReservation.objects.count() == 1  # only the first, committed reservation


def test_concurrent_dispatch_and_revocation_do_not_deadlock():
    from engine.services._model_allocation_lifecycle import revoke_model_generation

    allocation = make_reservable_allocation()
    outcome = reserve_request(
        allocation_id=allocation.pk,
        request_uuid=uuid4(),
        logical_alias="coding-main",
        billing_bound=_bound(1000),
    )

    def do_dispatch():
        try:
            open_dispatch(request_uuid=outcome.request_uuid)
            return "dispatched"
        except ContractError as exc:
            return exc.code

    def do_revoke():
        revoke_model_generation(allocation.range_id)
        return "revoked"

    results = _run_concurrently([do_dispatch, do_revoke])
    # Owner-first lock order means the two transactions serialise instead of
    # deadlocking: revocation always completes; dispatch either opened first or
    # was fenced as revoked. No OperationalError (deadlock) is raised.
    assert results.count("revoked") == 1
    assert set(results) <= {"revoked", "dispatched", "request.revoked"}


def test_concurrent_duplicate_settlement_charges_once():
    allocation = make_reservable_allocation()
    outcome = reserve_request(
        allocation_id=allocation.pk,
        request_uuid=uuid4(),
        logical_alias="coding-main",
        billing_bound=_bound(1000),
    )
    open_dispatch(request_uuid=outcome.request_uuid)
    usage = ProviderUsage(items=(VerifiedUsage(component="input_tokens", units=500, provider_verified=True),))

    def settle():
        return settle_request(request_uuid=outcome.request_uuid, usage=usage)

    _run_concurrently([settle, settle])
    account = ModelBudgetAccount.objects.get(account_ref="deployment-spend")
    assert account.spent == 1500  # settled exactly once despite concurrent settlement
    assert account.reserved == 0
    assert ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid).settlement_state == "settled"


def test_authority_mutation_and_admission_serialize_without_lock_inversion(monkeypatch):
    from django.db import transaction

    from engine.models import ModelAllocationAuthority, ModelPendingGrant, SharingAuthorityFence
    from engine.services import _model_request_accounting as accounting
    from engine.services._model_allocation_lifecycle import revoke_model_authorities

    allocation = make_reservable_allocation()
    fence = SharingAuthorityFence.objects.create(
        deployment_id=allocation.deployment_id,
        authority_owner="management",
        authority_reference="user:1",
        authority_revision=1,
        state="allowed",
    )
    ModelAllocationAuthority.objects.create(allocation=allocation, fence=fence, revision=1)
    grant_locked, fence_locked = threading.Event(), threading.Event()
    original = accounting._recheck_authority

    def paused_recheck(locked_allocation):
        grant_locked.set()
        assert fence_locked.wait(3)
        original(locked_allocation)

    monkeypatch.setattr(accounting, "_recheck_authority", paused_recheck)

    def reserve():
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '3s'")
            return _reserve_call(allocation)()

    def revoke():
        assert grant_locked.wait(3)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '3s'")
            SharingAuthorityFence.objects.filter(pk=fence.pk).update(authority_revision=2, state="revoked")
            fence_locked.set()
            return revoke_model_authorities([fence.pk])

    assert _run_concurrently([reserve, revoke]) == ["ok", 1]
    assert ModelPendingGrant.objects.get(allocation=allocation).state == "revoked"
