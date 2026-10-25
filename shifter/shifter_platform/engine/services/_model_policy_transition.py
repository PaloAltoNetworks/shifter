"""Explicit model-policy revisions within an unchanged range execution generation."""

from __future__ import annotations

from uuid import UUID

from django.db import transaction

from shared.model_access import ContractError

_RANGE_UNAVAILABLE = "source.range_unavailable"


def begin_range_model_policy_change(*, request_id: UUID, expected_revision: int, actor_id: int) -> int:
    """CMS authorizes the editor; commit fencing before replacement admission."""
    from engine.models import Range
    from engine.services._model_allocation_lifecycle import revoke_model_generation
    from shared.audit import AuditActorType, AuditEvent, audit_log

    with transaction.atomic():
        row = Range.objects.select_for_update().filter(request__request_id=request_id).first()
        if row is None or row.status != Range.Status.READY:
            raise ContractError(_RANGE_UNAVAILABLE)
        if type(expected_revision) is not int or row.model_source_policy_revision != expected_revision:
            raise ContractError("source.revision_conflict")
        revoke_model_generation(row.uuid, operation_id=row.provisioner_operation_id)
        row.model_source_policy_revision += 1
        row.save(update_fields=["model_source_policy_revision"])
        audit_log(
            AuditEvent(
                entity_type="range",
                entity_id=row.pk,
                action="update",
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                context=f"model source policy revision={row.model_source_policy_revision}",
            ),
            strict=True,
        )
        return row.model_source_policy_revision


def admit_range_model_policy_change(*, request_id: UUID, expected_revision: int) -> tuple[UUID, ...]:
    """Admit replacements from the freshly prepared snapshot, then link refresh."""
    from engine.models import ModelAccessCredential, ModelAllocation, Range
    from engine.services._model_allocation_launch import allocate_launch_models

    with transaction.atomic():
        row = Range.objects.select_for_update().get(request__request_id=request_id)
        if row.status != Range.Status.READY or row.model_source_policy_revision != expected_revision:
            raise ContractError("source.revision_conflict")
        if row.provisioner_operation_id is None:
            raise ContractError(_RANGE_UNAVAILABLE)
        previous = list(
            ModelAllocation.objects.filter(
                request_id=request_id,
                operation_id=row.provisioner_operation_id,
                source_policy_revision__lt=expected_revision,
            )
            .select_related("grant")
            .order_by("source_policy_revision")
        )
        allocations = allocate_launch_models(
            {"resource": "raes-range", "operation": "provision", "request_id": str(request_id)},
            row.provisioner_operation_id,
        )
        by_role = {allocation.workload_role: allocation for allocation in allocations}
        for prior in previous:
            successor = by_role.get(prior.workload_role)
            if successor is not None:
                ModelAccessCredential.objects.filter(grant=prior.grant).exclude(refresh_hash="").update(
                    replacement_grant=successor.grant
                )
        return tuple(allocation.pk for allocation in allocations)


def revoke_range_model_access(*, request_id: UUID, actor_id: int) -> int:
    """Fence a range's current model grants and dispatch leases (M09, #2126).

    CMS authorizes the range administrator; this transactionally revokes the
    current execution generation's model authorities. Success fences database
    authority but never proves provider cancellation, and it neither refunds spend
    nor releases outstanding liabilities, which remain under their original
    immutable price/account vector. Returns the number of authorities fenced.
    """
    from engine.models import Range
    from engine.services._model_allocation_lifecycle import revoke_model_generation
    from shared.audit import AuditActorType, AuditEvent, audit_log

    with transaction.atomic():
        row = Range.objects.select_for_update().filter(request__request_id=request_id).first()
        if row is None or row.provisioner_operation_id is None:
            raise ContractError(_RANGE_UNAVAILABLE)
        fenced = revoke_model_generation(row.uuid, operation_id=row.provisioner_operation_id)
        audit_log(
            AuditEvent(
                entity_type="range",
                entity_id=row.pk,
                action="model_access_revoke",
                actor_type=AuditActorType.USER,
                actor_id=actor_id,
                context=f"model access revoked authorities={fenced}",
            ),
            strict=True,
        )
        return fenced


def get_range_model_policy_status(*, request_id: UUID) -> dict[str, object]:
    """Bounded metadata for the current policy; retained allocations stay internal."""
    from engine.models import ModelAllocation, Range

    row = Range.objects.filter(request__request_id=request_id).first()
    if row is None or row.provisioner_operation_id is None:
        return {"state": "unavailable", "assignments": []}
    allocations = list(
        ModelAllocation.objects.filter(
            request_id=request_id,
            operation_id=row.provisioner_operation_id,
            source_policy_revision=row.model_source_policy_revision,
        )
        .select_related("grant")
        .order_by("workload_role")[:64]
    )
    states = {allocation.grant.state for allocation in allocations}
    state = "unavailable"
    if states == {"active"}:
        state = "active"
    elif states and states <= {"pending", "active"}:
        state = "refresh_pending"
    assignments = [
        {
            "workload": allocation.workload_role,
            "logical_alias": alias,
            "provider": shard["provider_adapter_id"],
            "model": shard["provider_model"],
            "region": shard["region"],
        }
        for allocation in allocations
        for alias, shard in allocation.snapshot["shards"].items()
    ]
    return {"state": state, "assignments": assignments}
