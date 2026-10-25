"""Original-generation cleanup, revocation, expiry and liability retention."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from engine.models import ModelCapacityReservation, Range
from engine.services import invalidate_sharing_authority
from shared.model_access import AuthorityInvalidation, ContractError

from .test_model_allocation import allocate, allocation_inputs

pytestmark = pytest.mark.django_db(transaction=True)


def test_replacement_uses_new_epoch_and_released_original_does_not_block_it(django_user_model):
    from uuid import uuid4

    from engine.models import Range
    from engine.services._model_allocation_lifecycle import release_model_allocation

    catalog, request, observations = allocation_inputs(django_user_model)
    first = allocate((catalog, request, observations))
    release_model_allocation(first.pk, operation_id=request.operation_id)
    operation = uuid4()
    Range.objects.filter(uuid=request.range_id).update(provisioner_operation_id=operation)
    replacement = allocate((catalog, request.model_copy(update={"operation_id": operation}), observations))
    first.grant.refresh_from_db()
    assert replacement.grant.grant_epoch > first.grant.grant_epoch
    assert replacement.draws.get().reservation_id != first.draws.get().reservation_id


def test_owner_invalidation_revokes_pending_grant_in_same_transaction(django_user_model):
    catalog, request, observations = allocation_inputs(django_user_model)
    allocation = allocate((catalog, request, observations))
    invalidate_sharing_authority(
        AuthorityInvalidation(
            deployment_id=catalog.deployment_id,
            authority_refs=(request.owner_ref,),
            state="revoked",
            reason="owner-removed",
        )
    )
    allocation.grant.refresh_from_db()
    assert allocation.grant.state == "revoked"
    assert allocation.grant.grant_epoch == 2
    with pytest.raises(ContractError, match=r"allocation\.revoked"):
        allocate((catalog, request, observations))


def test_late_cleanup_releases_only_original_generation(django_user_model):
    from engine.services._model_allocation_lifecycle import release_model_allocation

    catalog, request, observations = allocation_inputs(django_user_model)
    original = allocate((catalog, request, observations))
    operation_id = uuid4()
    Range.objects.filter(uuid=request.range_id).update(provisioner_operation_id=operation_id)
    successor_request = request.model_copy(update={"operation_id": operation_id, "scope_id": uuid4()})
    successor = allocate((catalog, successor_request, observations))
    assert release_model_allocation(original.pk, operation_id=request.operation_id)
    assert not release_model_allocation(original.pk, operation_id=request.operation_id)
    assert not release_model_allocation(successor.pk, operation_id=request.operation_id)
    successor.grant.refresh_from_db()
    assert successor.grant.state == "pending"
    assert successor.draws.get().released_at is None
    assert successor.draws.get().reservation.consumed == 4000


def test_expiry_retains_unresolved_liability_and_original_references(django_user_model):
    from engine.services._model_allocation_lifecycle import reconcile_model_allocations

    allocation = allocate(allocation_inputs(django_user_model))
    snapshot = allocation.snapshot
    allocation.deadline = timezone.now() - timedelta(seconds=1)
    allocation.unresolved_liabilities = 1
    allocation.save(update_fields=["deadline", "unresolved_liabilities"])
    reconcile_model_allocations()
    allocation.refresh_from_db()
    assert allocation.grant.state == "revoked"
    assert allocation.released_at is None
    assert ModelCapacityReservation.objects.get().consumed == 4000
    assert allocation.snapshot == snapshot


def test_scheduled_worker_releases_revoked_allocation_capacity(django_user_model):
    from cms.management.commands.reconcile_range_events import Command
    from engine.services._model_allocation_lifecycle import revoke_model_generation

    allocation = allocate(allocation_inputs(django_user_model))
    draw = allocation.draws.select_related("reservation").get()
    revoke_model_generation(allocation.range_id)

    Command()._run_once(stale_seconds=300, batch_size=100)

    allocation.refresh_from_db()
    draw.refresh_from_db()
    draw.reservation.refresh_from_db()
    assert allocation.released_at is not None
    assert draw.released_at is not None
    assert draw.reservation.consumed == 0


def test_reconcile_expires_only_unused_capacity_past_its_window(django_user_model):
    from engine.models import ModelCapacityReservation
    from engine.services._model_allocation_lifecycle import reconcile_model_allocations

    now = timezone.now()
    allocation = allocate(allocation_inputs(django_user_model))
    template = allocation.draws.select_related("reservation__quota", "reservation__assessment").get().reservation

    def reservation(scope_key, *, window_end, consumed):
        return ModelCapacityReservation.objects.create(
            quota=template.quota,
            assessment=template.assessment,
            scope_key=scope_key,
            window_start=now - timedelta(hours=2),
            window_end=window_end,
            amount=template.amount,
            consumed=consumed,
            observation=template.observation,
            workload_budgets={},
        )

    expired = reservation("event:unused-expired", window_end=now - timedelta(hours=1), consumed=0)
    future = reservation("event:unused-future", window_end=now + timedelta(hours=1), consumed=0)
    consumed = reservation("event:consumed-expired", window_end=now - timedelta(hours=1), consumed=1)

    reconcile_model_allocations(now=now)

    expired.refresh_from_db()
    future.refresh_from_db()
    consumed.refresh_from_db()
    assert expired.released_at == now
    assert future.released_at is None
    assert consumed.released_at is None
