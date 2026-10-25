"""Join CMS's trusted model inputs to the incumbent atomic launch outbox."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from uuid import UUID

from django.db import connection, transaction

from engine.models import ModelAllocation, ModelLaunchPreparationRecord, ModelOptionalAbsence, ModelQuotaReading, Range
from shared.model_access import ContractError, ModelAccessCatalog, OwnedReference, compute_digest, validate_catalog
from shared.model_access.core_models import ScenarioNeed
from shared.model_access.reservation import (
    AuthorityRevision,
    ModelAllocationRequest,
    ModelLaunchPreparation,
    ModelLaunchScope,
    ModelQuotaObservation,
)

from ._model_allocation import allocate_model_access
from ._model_allocation_contracts import validated
from ._model_allocation_lifecycle import revoke_model_generation

_INTENT_CONFLICT = "allocation.intent_conflict"


def project_model_launch_authority(
    *, deployment_id: UUID, authority_refs: tuple[OwnedReference, ...]
) -> tuple[AuthorityRevision, ...]:
    """Project facts freshly checked under owning-service locks by the caller.

    An internal downward bridge, like project_selector_resolution; never exposed
    as a client-controlled API. It cannot itself authenticate an owner.
    """
    from shared.model_access.reservation import AuthorityRevision

    from ._sharing_authority import _refresh_authority_fences

    with transaction.atomic():
        revisions = _refresh_authority_fences(deployment_id=deployment_id, authority_refs=authority_refs)
        return tuple(
            AuthorityRevision(authority_ref=ref, authority_revision=revisions[(ref.owner, ref.reference)])
            for ref in authority_refs
        )


def record_model_observations(
    catalog: ModelAccessCatalog,
    observer: Callable[[ModelAccessCatalog], Iterable[ModelQuotaObservation]],
) -> int:
    """Collect provider readings outside *every* enclosing transaction, then store.

    The observer is a qualified adapter supplied by the caller. An absent or
    failed adapter never fabricates healthy quota or calls the compute provider.
    """
    if connection.in_atomic_block:
        raise ContractError("allocation.observation_in_transaction")
    catalog = validate_catalog(catalog.model_dump(mode="json"))
    readings = tuple(validated(ModelQuotaObservation, item) for item in observer(catalog))
    pool_ids = {pool.quota_pool_id for pool in catalog.quota_pools}
    if len({item.quota_pool_id for item in readings}) != len(readings):
        raise ContractError("allocation.duplicate_observation")
    with transaction.atomic():
        for reading in sorted(readings, key=lambda item: item.quota_pool_id):
            if reading.catalog_digest != catalog.digest or reading.quota_pool_id not in pool_ids:
                raise ContractError("allocation.observation_mismatch")
            row, created = ModelQuotaReading.objects.get_or_create(
                catalog_digest=catalog.digest,
                quota_pool_id=reading.quota_pool_id,
                defaults={"observed_at": reading.observed_at, "observation": reading.model_dump(mode="json")},
            )
            if not created:
                row = ModelQuotaReading.objects.select_for_update().get(pk=row.pk)
                if reading.observed_at < row.observed_at:
                    raise ContractError("allocation.observation_regressed")
                if reading.observed_at == row.observed_at and reading.model_dump(mode="json") != row.observation:
                    raise ContractError("allocation.observation_conflict")
                row.observed_at = reading.observed_at
                row.observation = reading.model_dump(mode="json")
                row.save(update_fields=["observed_at", "observation"])
    return len(readings)


def prepare_model_launch(
    *,
    request_id: UUID,
    owner_ref: OwnedReference,
    needs: tuple[ScenarioNeed, ...],
    scope: ModelLaunchScope,
    authority_revisions: tuple[AuthorityRevision, ...],
    catalog: ModelAccessCatalog,
    replace_revoked: bool = False,
) -> ModelLaunchPreparationRecord:
    """Store reviewed downward inputs; this is not a grant or allocation."""
    intent = validated(
        ModelLaunchPreparation,
        {
            "request_id": request_id,
            "owner_ref": owner_ref,
            "needs": needs,
            "scope": scope,
            "authority_revisions": authority_revisions,
        },
    )
    catalog = validate_catalog(catalog.model_dump(mode="json"))
    digest = compute_digest({"intent": intent.model_dump(mode="json"), "catalog_digest": catalog.digest})
    with transaction.atomic():
        Range.objects.select_for_update().get(request__request_id=request_id)
        row, created = ModelLaunchPreparationRecord.objects.get_or_create(
            request_id=request_id,
            defaults={
                "intent_digest": digest,
                "intent": intent.model_dump(mode="json"),
                "catalog": catalog.model_dump(mode="json"),
            },
        )
        if not created and row.intent_digest != digest:
            if (
                not replace_revoked
                or ModelAllocation.objects.filter(
                    request_id=request_id, grant__state__in=["pending", "active"]
                ).exists()
            ):
                raise ContractError(_INTENT_CONFLICT)
            row.intent_digest = digest
            row.intent = intent.model_dump(mode="json")
            row.catalog = catalog.model_dump(mode="json")
            row.save(update_fields=["intent_digest", "intent", "catalog", "updated_at"])
    return row


def disable_optional_model_preparation(
    *, request_id: UUID, owner_ref: OwnedReference, needs: tuple[ScenarioNeed, ...]
) -> None:
    """Persist a replay-stable optional denial without fabricating policy scope."""
    intent = validated(
        ModelLaunchPreparation,
        {
            "request_id": request_id,
            "owner_ref": owner_ref,
            "needs": needs,
            "unavailable_reason": "allocation.policy_unavailable",
        },
    )
    payload = intent.model_dump(mode="json")
    digest = compute_digest({"intent": payload, "catalog_digest": None})
    with transaction.atomic():
        row = Range.objects.select_for_update().get(request__request_id=request_id)
        record, created = ModelLaunchPreparationRecord.objects.get_or_create(
            request_id=request_id,
            defaults={"intent_digest": digest, "intent": payload, "catalog": None},
        )
        if created:
            return
        revoke_model_generation(row.uuid)
        record.intent = payload
        record.intent_digest = digest
        record.catalog = None
        record.save(update_fields=["intent", "intent_digest", "catalog", "updated_at"])


def _record_absence(key: dict[str, object], digest: str, reason: str) -> None:
    """Persist one replay-stable optional absence decision."""
    row, created = ModelOptionalAbsence.objects.get_or_create(
        **key, defaults={"intent_digest": digest, "reason": reason}
    )
    if not created and (row.intent_digest != digest or row.reason != reason):
        raise ContractError(_INTENT_CONFLICT)


def _model_launch_request_id(payload: dict[str, object]) -> UUID | None:
    """Return a request identity only for model-aware launch resources."""
    if payload.get("resource") not in {"range", "raes-range"} or "request_id" not in payload:
        return None
    return UUID(str(payload["request_id"]))


def _load_launch_preparation(
    request_id: UUID, operation: str, operation_id: UUID
) -> tuple[Range, ModelLaunchPreparationRecord, ModelLaunchPreparation] | None:
    """Apply non-allocation operations and load one usable preparation."""
    range_obj = Range.objects.select_for_update().get(request__request_id=request_id)
    result = None
    if operation in {"pause", "destroy"}:
        revoke_model_generation(range_obj.uuid)
    else:
        prepared = ModelLaunchPreparationRecord.objects.filter(request_id=request_id).first()
        if prepared is not None:
            intent = validated(ModelLaunchPreparation, prepared.intent)
            if intent.unavailable_reason:
                for need in intent.needs:
                    _record_absence(
                        {
                            "request_id": request_id,
                            "operation_id": operation_id,
                            "workload_role": need.workload_role,
                        },
                        compute_digest({"preparation": prepared.intent_digest, "operation_id": str(operation_id)}),
                        intent.unavailable_reason,
                    )
            else:
                result = range_obj, prepared, intent
    return result


def allocate_launch_models(payload: dict[str, object], operation_id: UUID) -> tuple[ModelAllocation, ...]:
    """Called inside enqueue_provisioner_launch, before input and intent commit."""
    request_id = _model_launch_request_id(payload)
    if request_id is None:
        return ()
    operation = str(payload["operation"])
    prepared_launch = _load_launch_preparation(request_id, operation, operation_id)
    if prepared_launch is None:
        return ()
    range_obj, prepared, intent = prepared_launch
    if intent.scope is None or prepared.catalog is None:
        raise ContractError("allocation.invalid_input")
    catalog = validate_catalog(prepared.catalog)
    from ._model_source_observations import launch_model_observations

    observations = launch_model_observations(catalog)
    demands = {item.workload_role: item for item in intent.scope.demands}
    allocated = []
    for need in sorted(intent.needs, key=lambda item: item.workload_role):
        request = ModelAllocationRequest(
            deployment_id=catalog.deployment_id,
            request_id=request_id,
            operation_id=operation_id,
            range_id=range_obj.uuid,
            draw_key=intent.scope.draw_key,
            owner_ref=intent.owner_ref,
            subject_ref=intent.scope.subject_ref,
            scope_kind=intent.scope.kind,
            scope_id=intent.scope.scope_id,
            source_policy_revision=intent.scope.source_policy_revision,
            need=need,
            demand=demands[need.workload_role],
            window_start=intent.scope.window_start,
            window_end=intent.scope.window_end,
            authority_revisions=intent.authority_revisions,
            preparation_authority=intent.scope.system_preparation.authority_ref
            if intent.scope.system_preparation
            else None,
        )
        if request.preparation_authority is not None and operation != "provision":
            raise ContractError("allocation.system_preparation_only")
        allocation = _allocate_workload(request, catalog, observations)
        if allocation is not None:
            allocated.append(allocation)
    return tuple(allocated)


def _allocate_workload(
    request: ModelAllocationRequest,
    catalog: ModelAccessCatalog,
    observations: tuple[object, ...],
) -> ModelAllocation | None:
    """Record optional absence atomically, so a retry cannot turn it into access."""
    key = {
        "request_id": request.request_id,
        "operation_id": request.operation_id,
        "workload_role": request.need.workload_role,
        "source_policy_revision": request.source_policy_revision,
    }
    digest = compute_digest(request)
    absence = ModelOptionalAbsence.objects.filter(**key).first()
    if absence is not None:
        if absence.intent_digest != digest:
            raise ContractError(_INTENT_CONFLICT)
        return None
    try:
        return allocate_model_access(request, catalog=catalog, observations=observations, retire_previous=True)
    except ContractError as exc:
        absent_reasons = {
            "allocation.capacity_unavailable",
            "allocation.policy_unavailable",
            "allocation.capability_unavailable",
            "allocation.price_unavailable",
            "allocation.provider_pool_unavailable",
            "allocation.alias_unavailable",
            "allocation.strategy_not_allowed",
            "allocation.shared_assignment_incompatible",
            "allocation.authority_unavailable",
            "allocation.authority_changed",
            "allocation.egress_incompatible",
            "allocation.unsupported_metric",
            "allocation.shared_pool_required",
            "allocation.expired",
            "allocation.revoked",
        }
        if request.need.required or exc.code not in absent_reasons:
            raise
        _record_absence(key, digest, exc.code)
        return None
