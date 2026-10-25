"""Import-safe public model admission bridges (Engine loads before app registry)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from engine.models import ModelLaunchPreparationRecord, SharingAuthorityFence
    from shared.model_access import ModelAccessCatalog, OwnedReference, SharingBinding
    from shared.model_access.core_models import ScenarioNeed
    from shared.model_access.reservation import (
        AuthorityRevision,
        ModelLaunchPreparation,
        ModelLaunchScope,
        ModelQuotaObservation,
        ModelWarmScope,
    )


def fence_model_policy_publication(deployment_id: UUID) -> SharingAuthorityFence:
    """Take the publication writer lock after owner resolution, before projection.

    The composition caller must keep its owning transaction open through binding
    publication; the binding service then reuses this lock, never inverts it.
    """
    from django.db import connection

    from shared.model_access import ContractError

    from ._model_allocation_authority import lock_policy_publication

    if not connection.in_atomic_block:
        raise ContractError("allocation.publication_transaction_required")
    return lock_policy_publication(deployment_id, writing=True)


def list_model_launch_refreshes(deployment_id: UUID) -> tuple[SharingBinding, ...]:
    """Read the published definitions whose current owner evidence needs refreshing."""
    from ._model_allocation_authority import list_model_launch_refreshes as read

    return read(deployment_id)


def get_model_warm_scope(request_id: UUID, *, deployment_id: UUID) -> ModelWarmScope | None:
    """Project the locked warm ledger through its owning Engine service."""
    from ._model_warm_authority import project_warm_scope

    return project_warm_scope(request_id, deployment_id=deployment_id)


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
    """Persist closed downward launch inputs without dispatching or issuing access."""
    from ._model_allocation_launch import prepare_model_launch as prepare

    return prepare(
        request_id=request_id,
        owner_ref=owner_ref,
        needs=needs,
        scope=scope,
        authority_revisions=authority_revisions,
        catalog=catalog,
        replace_revoked=replace_revoked,
    )


def get_model_launch_preparation(request_id: UUID) -> ModelLaunchPreparation | None:
    """Read the immutable package needs that lifecycle refresh must preserve."""
    from engine.models import ModelLaunchPreparationRecord
    from shared.model_access.reservation import ModelLaunchPreparation

    from ._model_allocation_contracts import validated

    row = ModelLaunchPreparationRecord.objects.filter(request_id=request_id).first()
    return validated(ModelLaunchPreparation, row.intent) if row is not None else None


def disable_optional_model_preparation(
    *, request_id: UUID, owner_ref: OwnedReference, needs: tuple[ScenarioNeed, ...]
) -> None:
    """Persist optional policy absence without erasing the original package needs."""
    from ._model_allocation_launch import disable_optional_model_preparation as disable

    return disable(request_id=request_id, owner_ref=owner_ref, needs=needs)


def project_model_launch_authority(
    *, deployment_id: UUID, authority_refs: tuple[OwnedReference, ...]
) -> tuple[AuthorityRevision, ...]:
    """Project facts the caller checked under owning-service locks."""
    from ._model_allocation_launch import project_model_launch_authority as project

    return project(deployment_id=deployment_id, authority_refs=authority_refs)


def record_model_observations(
    catalog: ModelAccessCatalog,
    observer: Callable[[ModelAccessCatalog], Iterable[ModelQuotaObservation]],
) -> int:
    """Collect qualified observations outside transactions and persist their provenance."""
    from ._model_allocation_launch import record_model_observations as record

    return record(catalog, observer)
