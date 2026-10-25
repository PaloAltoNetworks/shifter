"""Generation-scoped grant fencing and conservative model-capacity cleanup."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from engine.models import ModelAllocation, ModelCapacityReservation, ModelPendingGrant, ModelQuotaIdentity, Range

logger = logging.getLogger(__name__)


def revoke_model_authorities(fence_ids: Iterable[int]) -> int:
    """Fence each dependent pending grant once in the owner's transaction."""
    grants = ModelPendingGrant.objects.filter(
        allocation__authorities__fence_id__in=fence_ids,
        state__in=["pending", "active"],
    )
    allocation_ids = list(grants.values_list("allocation_id", flat=True))
    revoked = grants.update(state="revoked", grant_epoch=F("grant_epoch") + 1, revoked_at=timezone.now())
    _fence_allocation_requests(allocation_ids)
    return revoked


def revoke_model_generation(range_id: UUID, *, operation_id: UUID | None = None) -> int:
    """Invalidate original access before lifecycle transition/re-admission."""
    grants = ModelPendingGrant.objects.filter(allocation__range_id=range_id, state__in=["pending", "active"])
    if operation_id is not None:
        grants = grants.filter(allocation__operation_id=operation_id)
    allocation_ids = list(grants.values_list("allocation_id", flat=True))
    revoked = grants.update(state="revoked", grant_epoch=F("grant_epoch") + 1, revoked_at=timezone.now())
    _fence_allocation_requests(allocation_ids)
    return revoked


def _fence_allocation_requests(allocation_ids: Iterable[UUID]) -> None:
    """Mark in-flight request dispatch leases revoking after a grant epoch is fenced."""
    from ._model_request_lifecycle import fence_revoked_requests

    for allocation_id in allocation_ids:
        fence_revoked_requests(allocation_id=allocation_id)


def _release_locked(allocation: ModelAllocation, now: datetime) -> bool:
    """Revoke and release an already locked allocation and its child draws."""
    if allocation.released_at is not None:
        return False
    ModelPendingGrant.objects.filter(allocation=allocation, state__in=["pending", "active"]).update(
        state="revoked",
        grant_epoch=F("grant_epoch") + 1,
        revoked_at=now,
    )
    if allocation.unresolved_liabilities:
        return False
    for draw in (
        allocation.draws.filter(released_at__isnull=True)
        .select_related("reservation")
        .order_by("reservation__quota_id", "reservation_id")
    ):
        parent = draw.reservation
        parent.consumed -= draw.amount
        parent.workload_budgets[allocation.workload_role]["consumed"] -= draw.amount
        if parent.consumed == 0 and (parent.scope_key.startswith(("standalone:", "warm:")) or parent.window_end <= now):
            parent.released_at = now
        parent.save(update_fields=["consumed", "released_at", "workload_budgets"])
        draw.released_at = now
        draw.save(update_fields=["released_at"])
    allocation.released_at = now
    allocation.save(update_fields=["released_at"])
    return True


def release_model_allocation(allocation_id: UUID, *, operation_id: UUID, now: datetime | None = None) -> bool:
    """Release this exact allocation only when it has no unresolved liability.

    A shared/event commitment survives member release until its original window
    expires. Original snapshots and closed draws remain as tombstones.
    """
    now = now or timezone.now()
    with transaction.atomic():
        candidate = ModelAllocation.objects.filter(pk=allocation_id, operation_id=operation_id).first()
        if candidate is None:
            return False
        Range.objects.select_for_update().filter(uuid=candidate.range_id).first()
        quotas = candidate.draws.values_list("reservation__quota_id", flat=True)
        tuple(ModelQuotaIdentity.objects.select_for_update().filter(pk__in=quotas).order_by("pk"))
        allocation = ModelAllocation.objects.select_for_update().get(pk=allocation_id)
        return _release_locked(allocation, now)


def reconcile_model_allocations(*, now: datetime | None = None, limit: int = 100) -> int:
    """Bounded expiry/revocation cleanup invoked by the incumbent reconciler."""
    now = now or timezone.now()
    terminal = Range.objects.filter(status__in=[Range.Status.DESTROYED, Range.Status.FAILED]).values_list(
        "uuid", flat=True
    )
    candidates = list(
        ModelAllocation.objects.filter(released_at__isnull=True)
        .filter(
            Q(deadline__lte=now) | Q(grant__state="revoked") | Q(range_id__in=terminal),
        )
        .order_by("deadline", "pk")[:limit]
    )
    released = sum(release_model_allocation(item.pk, operation_id=item.operation_id, now=now) for item in candidates)
    # Unused shared/event parents expire too. The real-quota mutex is the same
    # one allocation/release use; never take a draw lock before its parent.
    expired = ModelCapacityReservation.objects.filter(released_at__isnull=True, window_end__lte=now, consumed=0)
    for quota_id in expired.values_list("quota_id", flat=True).distinct()[:limit]:
        with transaction.atomic():
            ModelQuotaIdentity.objects.select_for_update().get(pk=quota_id)
            expired.filter(quota_id=quota_id).update(released_at=now)
    lag = max((max(0, (now - item.deadline).total_seconds()) for item in candidates), default=0)
    logger.info(
        "model-access reconciliation",
        extra={
            "model_access_namespace": "Shifter/ModelAccess",
            "model_access_released": released,
            "model_access_expiry_lag_seconds": lag,
        },
    )
    _reconcile_requests_isolated(now=now, limit=limit)
    return released


def _reconcile_requests_isolated(*, now: datetime, limit: int) -> None:
    """Run the bounded request-accounting reconciliation pass, isolated from failure."""
    from ._model_request_reconcile import (
        close_expired_revocations,
        reconcile_expired_dispatches,
        reconcile_model_requests,
    )

    try:
        reconcile_expired_dispatches(now=now, limit=limit)
        reconcile_model_requests(now=now, limit=limit)
        close_expired_revocations(now=now, limit=limit)
    except Exception:
        logger.exception("model-access request reconciliation pass failed")
