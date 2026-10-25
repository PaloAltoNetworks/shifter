"""Warm-ledger authority for model preparation and atomic claim revocation."""

from __future__ import annotations

from uuid import UUID

from django.db import connection
from django.utils import timezone

from engine.models import Range, WarmRangeGeneration
from shared.model_access import AuthorityInvalidation, AuthorityState, ContractError, OwnedReference
from shared.model_access.authority_port import invalidate_authority
from shared.model_access.reservation import ModelWarmScope


def _reference(generation_id: UUID) -> OwnedReference:
    """Build the stable Engine authority identity for one generation."""
    return OwnedReference(owner="engine", reference=f"warm-generation:{generation_id}")


def project_warm_scope(request_id: UUID, *, deployment_id: UUID) -> ModelWarmScope | None:
    """Prove one unclaimed, unexpired ledger row while its caller holds the transaction.

    The owner takes the generation mutex before Range and authority fences. The
    allocator only consumes that fence; it never locks the warm row in reverse.
    """
    from ._model_allocation_launch import project_model_launch_authority

    if not connection.in_atomic_block:
        raise ContractError("allocation.preparation_transaction_required")
    rows = list(
        WarmRangeGeneration.objects.select_for_update().filter(
            request_id=request_id,
            state__in=WarmRangeGeneration.NONTERMINAL_UNCLAIMED_STATES,
            claimed_by_request_id__isnull=True,
            idle_deadline__gt=timezone.now(),
        )[:2]
    )
    if len(rows) != 1:
        return None
    row = rows[0]
    assert row.idle_deadline is not None
    realized = Range.objects.select_for_update().filter(request__request_id=request_id).first()
    if realized is None or (row.range_id is not None and row.range_id != realized.pk):
        raise ContractError("allocation.generation_mismatch")
    revisions = project_model_launch_authority(deployment_id=deployment_id, authority_refs=(_reference(row.uuid),))
    return ModelWarmScope(
        generation_id=row.uuid,
        scope_id=row.capacity_scope_ref,
        draw_key=row.capacity_draw_key,
        window_start=row.created_at,
        window_end=row.idle_deadline,
        authority_revisions=revisions,
    )


def invalidate_warm_preparation(instance: WarmRangeGeneration) -> None:
    """Fence preparation on claim/retirement or changes to captured ledger facts."""
    # Keep the same Range -> authority order as allocation, including when claim
    # invalidation runs before ownership transfer takes the Range mutex itself.
    if connection.in_atomic_block:
        tuple(Range.objects.select_for_update().filter(request__request_id=instance.request_id))
    invalidate_authority(
        AuthorityInvalidation(
            deployment_id=None,
            authority_refs=(_reference(instance.uuid),),
            state=AuthorityState.UNKNOWN,
            reason="warm-preparation-changed",
        )
    )
