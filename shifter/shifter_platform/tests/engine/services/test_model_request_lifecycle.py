"""Behavioural tests for dispatch leases, settlement and reconciliation (M04)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from engine.models import (
    ModelAllocation,
    ModelBudgetAccount,
    ModelDispatchLease,
    ModelPendingGrant,
    ModelReconciliationObligation,
    ModelRequestReservation,
)
from engine.services import (
    apply_late_evidence,
    charge_unknown,
    close_expired_revocations,
    commit_request_spend,
    fence_revoked_requests,
    open_dispatch,
    reconcile_model_requests,
    release_before_dispatch,
    renew_continuation_lease,
    reserve_request,
    settle_request,
)
from shared.model_access import BillingBound, ContractError
from shared.model_access.core_models import BillingComponent
from shared.model_access.provider import BillingAmount, ProviderUsage, VerifiedUsage

from .model_broker_http_support import enable_count
from .test_model_request_accounting import _bound, failing_audit_writer, make_reservable_allocation

pytestmark = pytest.mark.django_db


def _reserve(allocation, **overrides):
    values = {
        "allocation_id": allocation.pk,
        "request_uuid": uuid4(),
        "logical_alias": "coding-main",
        "billing_bound": _bound(),
    }
    values.update(overrides)
    return reserve_request(**values)


def _usage(units, *, verified=True):
    return ProviderUsage(items=(VerifiedUsage(component="input_tokens", units=units, provider_verified=verified),))


def _multi_bound():
    from shared.model_access import BillingBound
    from shared.model_access.provider import BillingAmount

    return BillingBound(
        amounts=(
            BillingAmount(component="input_tokens", units=1000, maximum_charge_micro_units=0),
            BillingAmount(component="output_tokens", units=500, maximum_charge_micro_units=0),
        )
    )


def _spend():
    return ModelBudgetAccount.objects.get(account_ref="deployment-spend")


def _concurrency():
    return ModelBudgetAccount.objects.get(account_ref="deployment-concurrency")


def _count_bound():
    return BillingBound(
        amounts=(BillingAmount(component=BillingComponent.REQUEST, units=1, maximum_charge_micro_units=0),)
    )


def _paid_bound(input_tokens, output_tokens=10):
    return BillingBound(
        amounts=(
            BillingAmount(component=BillingComponent.INPUT_TOKENS, units=input_tokens, maximum_charge_micro_units=0),
            BillingAmount(component=BillingComponent.OUTPUT_TOKENS, units=output_tokens, maximum_charge_micro_units=0),
        )
    )


def test_commit_narrows_a_counted_reservation_to_the_proven_input_and_settles():
    allocation = make_reservable_allocation()
    enable_count(allocation)
    outcome = _reserve(allocation, billing_bound=_count_bound())  # free count admission: zero spend
    assert outcome.canonical_request_cost == 0
    open_dispatch(request_uuid=outcome.request_uuid)

    cost = commit_request_spend(request_uuid=outcome.request_uuid, billing_bound=_paid_bound(12))

    assert cost == 12 * 3 + 10 * 15  # input 3 micro/token, output 15 micro/token, from the snapshot schedule
    reservation = ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid)
    assert sorted(reservation.billed_components) == ["input_tokens", "output_tokens"]
    assert reservation.canonical_request_cost == cost
    spend = ModelBudgetAccount.objects.get(account_ref="deployment-spend")
    assert spend.reserved == cost
    # Settlement against the committed bound charges the proven usage exactly once.
    usage = ProviderUsage(
        items=(
            VerifiedUsage(component="input_tokens", units=12, provider_verified=True),
            VerifiedUsage(component="output_tokens", units=10, provider_verified=True),
        )
    )
    assert settle_request(request_uuid=outcome.request_uuid, usage=usage) == cost


def test_commit_denies_when_the_proven_input_would_exceed_the_spend_ceiling():
    allocation = make_reservable_allocation(spend_ceiling=100)
    enable_count(allocation)
    outcome = _reserve(allocation, billing_bound=_count_bound())
    open_dispatch(request_uuid=outcome.request_uuid)
    with pytest.raises(ContractError, match="budget_exceeded"):
        commit_request_spend(request_uuid=outcome.request_uuid, billing_bound=_paid_bound(1000))


def test_commit_rejects_a_reservation_that_already_carries_a_spend_bound():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)  # ordinary full input bound, not a count-first reservation
    open_dispatch(request_uuid=outcome.request_uuid)
    with pytest.raises(ContractError, match="commit_state"):
        commit_request_spend(request_uuid=outcome.request_uuid, billing_bound=_paid_bound(12))


def test_open_dispatch_acquires_single_short_lease():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    grant = open_dispatch(request_uuid=outcome.request_uuid)
    assert grant.dispatch_token
    reservation = ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid)
    assert reservation.state == "dispatched"
    assert ModelDispatchLease.objects.filter(reservation=reservation).count() == 1
    # A dispatched request cannot acquire a second attempt.
    with pytest.raises(ContractError, match=r"request\.dispatch_state"):
        open_dispatch(request_uuid=outcome.request_uuid)


def test_open_dispatch_denies_revoked_grant():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    ModelPendingGrant.objects.filter(allocation=allocation).update(grant_epoch=2)
    with pytest.raises(ContractError, match=r"request\.revoked"):
        open_dispatch(request_uuid=outcome.request_uuid)


def test_continuation_lease_advances_and_fences_on_revocation():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    assert renew_continuation_lease(request_uuid=outcome.request_uuid) == 1
    assert renew_continuation_lease(request_uuid=outcome.request_uuid) == 2
    fence_revoked_requests(allocation_id=allocation.pk)
    with pytest.raises(ContractError, match=r"request\.revoked"):
        renew_continuation_lease(request_uuid=outcome.request_uuid)


def test_settle_charges_actual_and_releases_unused():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)  # reserves 3000
    open_dispatch(request_uuid=outcome.request_uuid)
    settled = settle_request(request_uuid=outcome.request_uuid, usage=_usage(500))
    assert settled == 1500
    spend = _spend()
    assert spend.spent == 1500
    assert spend.reserved == 0  # the 3000 hold released, only proven 1500 charged
    assert _concurrency().active_leases == 0


def test_source_price_is_used_for_both_hold_and_settlement():
    """The selected provider's immutable price survives later source changes."""
    from copy import deepcopy

    from shared.model_access import seal_catalog

    allocation = make_reservable_allocation()
    payload = deepcopy(allocation.snapshot["catalog"])
    payload["contract_version"] = "model-access-policy/v4"
    selected_price = deepcopy(payload["price_schedules"][0])
    selected_price["price_schedule_id"] = "selected-source-price"
    selected_price["prices"][0]["price_micro_units"] = 7_000_000
    payload["price_schedules"].append(selected_price)
    source_id = uuid4()
    payload["shards"][0]["credential_ref"] = {"owner": "broker", "reference": f"source:{source_id}:2"}
    payload["source_bindings"] = [
        {
            "shard_id": "vertex-primary",
            "source_id": str(source_id),
            "source_revision": 2,
            "credential_revision": 2,
            "price_schedule_id": "selected-source-price",
        }
    ]
    allocation.snapshot["catalog"] = seal_catalog(payload).model_dump(mode="json")
    allocation.save(update_fields=["snapshot"])
    outcome = _reserve(allocation)
    assert outcome.canonical_request_cost == 7000
    open_dispatch(request_uuid=outcome.request_uuid)
    assert settle_request(request_uuid=outcome.request_uuid, usage=_usage(500)) == 3500
    assert _spend().spent == 3500
    assert _spend().reserved == 0


def test_settle_is_idempotent():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    settle_request(request_uuid=outcome.request_uuid, usage=_usage(500))
    again = settle_request(request_uuid=outcome.request_uuid, usage=_usage(999))
    assert again == 1500  # second call does not re-charge
    assert _spend().spent == 1500


def test_release_before_dispatch_frees_money_and_concurrency_keeps_rate():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    release_before_dispatch(request_uuid=outcome.request_uuid)
    assert _spend().reserved == 0
    assert _concurrency().active_leases == 0
    rate = ModelBudgetAccount.objects.get(account_ref="deployment-rate")
    assert rate.requests == 1  # abuse-rate accounting retained


def test_charge_unknown_retains_hold_and_records_obligation():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    charge_unknown(request_uuid=outcome.request_uuid, uncertainty_reason="timeout")
    spend = _spend()
    assert spend.reserved == 3000  # conservative hold retained, not refunded
    assert spend.spent == 0
    reservation = ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid)
    assert reservation.state == "unknown"
    assert ModelReconciliationObligation.objects.filter(reservation=reservation, outcome="unknown").count() == 1


def test_reconcile_moves_unknown_hold_to_spent_without_refund():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    charge_unknown(request_uuid=outcome.request_uuid, uncertainty_reason="timeout", horizon_seconds=0)
    processed = reconcile_model_requests(now=datetime.now(UTC) + timedelta(seconds=1))
    assert processed == 1
    spend = _spend()
    assert spend.spent == 3000  # conservative bound charged, same value
    assert spend.reserved == 0
    reservation = ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid)
    assert reservation.settlement_state == "unknown_charged"
    assert ModelReconciliationObligation.objects.get(reservation=reservation).outcome == "charged"


def test_reconcile_skips_obligations_not_yet_due():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    charge_unknown(request_uuid=outcome.request_uuid, uncertainty_reason="timeout", horizon_seconds=3600)
    assert reconcile_model_requests(now=datetime.now(UTC)) == 0
    assert _spend().reserved == 3000


def test_late_evidence_adjusts_charge_once():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    charge_unknown(request_uuid=outcome.request_uuid, uncertainty_reason="timeout", horizon_seconds=0)
    reconcile_model_requests(now=datetime.now(UTC) + timedelta(seconds=1))
    adjusted = apply_late_evidence(request_uuid=outcome.request_uuid, usage=_usage(500))
    assert adjusted == 1500
    assert _spend().spent == 1500  # append-only adjustment from authoritative evidence
    reservation = ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid)
    assert reservation.settlement_state == "settled"


def test_revoke_model_generation_fences_in_flight_requests():
    from engine.services._model_allocation_lifecycle import revoke_model_generation

    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    revoke_model_generation(allocation.range_id)
    reservation = ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid)
    assert ModelDispatchLease.objects.get(reservation=reservation).transport_status == "revoking"
    with pytest.raises(ContractError, match=r"request\.revoked"):
        renew_continuation_lease(request_uuid=outcome.request_uuid)


def test_incumbent_reconciler_runs_the_request_pass():
    from engine.services._model_allocation_lifecycle import reconcile_model_allocations

    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    charge_unknown(request_uuid=outcome.request_uuid, uncertainty_reason="timeout", horizon_seconds=0)
    reconcile_model_allocations(now=datetime.now(UTC) + timedelta(seconds=1))
    assert _spend().spent == 3000  # the request accounting pass charged the retained hold


def test_settle_incomplete_usage_retains_hold_and_reconciles():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    with pytest.raises(ContractError, match=r"request\.usage_incomplete"):
        settle_request(request_uuid=outcome.request_uuid, usage=ProviderUsage(items=()))
    spend = _spend()
    assert spend.reserved == 3000  # conservative hold retained, not released for free
    assert spend.spent == 0
    reservation = ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid)
    assert reservation.state == "unknown"
    assert ModelReconciliationObligation.objects.filter(reservation=reservation, outcome="unknown").exists()


def test_settle_unverified_usage_does_not_finalize():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    with pytest.raises(ContractError, match=r"request\.usage_incomplete"):
        settle_request(request_uuid=outcome.request_uuid, usage=_usage(500, verified=False))
    assert _spend().reserved == 3000
    assert _spend().spent == 0


def test_renew_rejects_expired_lease():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    with pytest.raises(ContractError, match=r"request\.lease_expired"):
        renew_continuation_lease(request_uuid=outcome.request_uuid, now=datetime.now(UTC) + timedelta(seconds=30))


def test_check_dispatch_lease_validates_token_and_deadline():
    from engine.services import check_dispatch_lease

    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    grant = open_dispatch(request_uuid=outcome.request_uuid)
    assert check_dispatch_lease(request_uuid=outcome.request_uuid, dispatch_token=grant.dispatch_token) is True
    with pytest.raises(ContractError, match=r"request\.lease_token_mismatch"):
        check_dispatch_lease(request_uuid=outcome.request_uuid, dispatch_token="wrong-token")
    with pytest.raises(ContractError, match=r"request\.lease_expired"):
        check_dispatch_lease(
            request_uuid=outcome.request_uuid,
            dispatch_token=grant.dispatch_token,
            now=datetime.now(UTC) + timedelta(seconds=30),
        )


def test_reconcile_expired_dispatches_records_unknown_and_charges():
    from engine.services import reconcile_expired_dispatches

    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    # A worker crashed after dispatch; its lease expires without settle/unknown.
    later = datetime.now(UTC) + timedelta(seconds=30)
    assert reconcile_expired_dispatches(now=later) == 1
    reservation = ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid)
    assert reservation.state == "unknown"
    assert _spend().reserved == 3000  # hold retained through the sweep, not released
    # The obligation is due immediately, so the request pass conservatively charges it.
    reconcile_model_requests(now=later)
    assert _spend().spent == 3000


def test_open_dispatch_rechecks_authority():
    from engine.models import ModelAllocationAuthority, SharingAuthorityFence

    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    fence = SharingAuthorityFence.objects.create(
        deployment_id=allocation.deployment_id,
        authority_owner="ctf",
        authority_reference="event:1",
        authority_revision=1,
        state="allowed",
    )
    ModelAllocationAuthority.objects.create(allocation=allocation, fence=fence, revision=1)
    fence.authority_revision = 2  # bulk membership change advanced the fence
    fence.save(update_fields=["authority_revision"])
    with pytest.raises(ContractError, match=r"request\.authority_changed"):
        open_dispatch(request_uuid=outcome.request_uuid)


def test_open_dispatch_denies_expired_allocation():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    ModelAllocation.objects.filter(pk=allocation.pk).update(deadline=timezone.now() - timedelta(seconds=1))
    with pytest.raises(ContractError, match=r"request\.allocation_expired"):
        open_dispatch(request_uuid=outcome.request_uuid)


def test_settle_requires_every_bounded_component():
    allocation = make_reservable_allocation()
    outcome = reserve_request(
        allocation_id=allocation.pk,
        request_uuid=uuid4(),
        logical_alias="coding-main",
        billing_bound=_multi_bound(),
    )
    open_dispatch(request_uuid=outcome.request_uuid)
    # Usage covers only input_tokens; output_tokens was bounded too, so it is incomplete
    # and must not release the hold as if output cost zero.
    only_input = ProviderUsage(items=(VerifiedUsage(component="input_tokens", units=500, provider_verified=True),))
    with pytest.raises(ContractError, match=r"request\.usage_incomplete"):
        settle_request(request_uuid=outcome.request_uuid, usage=only_input)
    assert _spend().reserved > 0  # conservative hold retained


def test_late_evidence_rejects_incomplete_usage():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    charge_unknown(request_uuid=outcome.request_uuid, uncertainty_reason="timeout", horizon_seconds=0)
    reconcile_model_requests(now=datetime.now(UTC) + timedelta(seconds=1))
    charged = _spend().spent
    with pytest.raises(ContractError, match=r"request\.usage_incomplete"):
        apply_late_evidence(request_uuid=outcome.request_uuid, usage=ProviderUsage(items=()))
    assert _spend().spent == charged  # conservative charge never erased by empty evidence


def test_settle_writes_a_body_free_audit_row():
    from shared.models import AuditLog

    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    settle_request(request_uuid=outcome.request_uuid, usage=_usage(500))
    row = AuditLog.objects.get(entity_ref=str(outcome.request_uuid), action="request_settle")
    assert row.entity_type == "model_request"
    assert "prompt" not in row.context.lower()


def test_strict_audit_failure_rolls_back_settlement():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    with failing_audit_writer(), pytest.raises(RuntimeError):
        settle_request(request_uuid=outcome.request_uuid, usage=_usage(500))
    reservation = ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid)
    assert reservation.settlement_state == "open"  # settlement rolled back with the audit
    assert _spend().reserved == 3000
    assert _spend().spent == 0


def test_scheduled_worker_runs_the_request_pass():
    from cms.management.commands.reconcile_range_events import Command

    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    charge_unknown(request_uuid=outcome.request_uuid, uncertainty_reason="timeout", horizon_seconds=0)
    Command()._run_once(stale_seconds=300, batch_size=100)
    assert _spend().spent == 3000  # the incumbent scheduled reconciler settled the retained hold


def test_close_expired_revocations_transitions_to_revoked():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    fence_revoked_requests(allocation_id=allocation.pk)
    reservation = ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid)
    assert ModelDispatchLease.objects.get(reservation=reservation).transport_status == "revoking"
    closed = close_expired_revocations(now=datetime.now(UTC) + timedelta(seconds=30))
    assert closed == 1
    assert ModelDispatchLease.objects.get(reservation=reservation).transport_status == "revoked"


@pytest.mark.parametrize("operation", ["dispatch", "check", "renew"])
def test_allocation_expiry_fences_every_transport_lease(operation):
    from engine.services import check_dispatch_lease

    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    lease = None
    if operation != "dispatch":
        lease = open_dispatch(request_uuid=outcome.request_uuid)
    allocation.deadline = datetime.now(UTC) - timedelta(seconds=1)
    allocation.save(update_fields=["deadline"])
    with pytest.raises(ContractError, match=r"request\.allocation_expired"):
        if operation == "dispatch":
            open_dispatch(request_uuid=outcome.request_uuid)
        elif operation == "check":
            check_dispatch_lease(request_uuid=outcome.request_uuid, dispatch_token=lease.dispatch_token)
        else:
            renew_continuation_lease(request_uuid=outcome.request_uuid)


def test_settlement_after_conservative_charge_adjusts_instead_of_double_charging():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    charge_unknown(request_uuid=outcome.request_uuid, uncertainty_reason="timeout", horizon_seconds=0)
    reconcile_model_requests(now=datetime.now(UTC) + timedelta(seconds=1))
    assert _spend().spent == 3000
    assert settle_request(request_uuid=outcome.request_uuid, usage=_usage(500)) == 1500
    assert _spend().spent == 1500
    assert settle_request(request_uuid=outcome.request_uuid, usage=_usage(500)) == 1500
    assert _spend().spent == 1500


@pytest.mark.parametrize("usage", [ProviderUsage(items=()), _usage(0, verified=False)])
def test_unverified_late_evidence_cannot_refund_conservative_charge(usage):
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    charge_unknown(request_uuid=outcome.request_uuid, uncertainty_reason="timeout", horizon_seconds=0)
    reconcile_model_requests(now=datetime.now(UTC) + timedelta(seconds=1))
    with pytest.raises(ContractError, match=r"request\.usage_incomplete"):
        apply_late_evidence(request_uuid=outcome.request_uuid, usage=usage)
    assert _spend().spent == 3000


def test_missing_usage_component_cannot_release_a_hold():
    from shared.model_access import BillingAmount, BillingBound

    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    # Preserve a second admitted component to demonstrate missing usage denial.
    reservation = ModelRequestReservation.objects.get(request_uuid=outcome.request_uuid)
    reservation.billing_bound = BillingBound(
        amounts=(
            BillingAmount(component="input_tokens", units=1000, maximum_charge_micro_units=0),
            BillingAmount(component="output_tokens", units=1000, maximum_charge_micro_units=0),
        )
    ).model_dump(mode="json")
    reservation.save(update_fields=["billing_bound"])
    with pytest.raises(ContractError, match=r"request\.usage_incomplete"):
        settle_request(request_uuid=outcome.request_uuid, usage=_usage(500))
    assert _spend().reserved == 3000
    assert _spend().spent == 0


def test_usage_above_bound_is_not_silently_clipped():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    with pytest.raises(ContractError, match=r"request\.usage_exceeds_bound"):
        settle_request(request_uuid=outcome.request_uuid, usage=_usage(2000))
    assert _spend().reserved == 3000


def test_crash_before_dispatch_releases_hold_but_preserves_rate_count():
    from engine.services import reconcile_expired_dispatches

    allocation = make_reservable_allocation()
    _reserve(allocation)
    assert reconcile_expired_dispatches(now=datetime.now(UTC) + timedelta(seconds=121)) == 1
    assert _spend().reserved == 0
    assert _concurrency().active_leases == 0
    assert ModelBudgetAccount.objects.get(account_ref="deployment-rate").requests == 1
    allocation.refresh_from_db()
    assert allocation.unresolved_liabilities == 0


def test_continuation_cannot_extend_request_hard_deadline():
    allocation = make_reservable_allocation()
    outcome = _reserve(allocation)
    open_dispatch(request_uuid=outcome.request_uuid)
    ModelRequestReservation.objects.filter(request_uuid=outcome.request_uuid).update(
        created_at=datetime.now(UTC) - timedelta(seconds=121),
    )
    with pytest.raises(ContractError, match=r"request\.deadline_expired"):
        renew_continuation_lease(request_uuid=outcome.request_uuid)
