"""Resolve CMS-owned model launch facts before the atomic Engine outbox write."""

from typing import Literal, cast
from uuid import UUID

from django.conf import settings
from django.db import transaction

from cms.models import RangeInstance
from cms.scenarios.model_needs import project_scenario_model_needs
from shared.model_access import ContractError, EventModelDemand, ModelAccessCatalog, OwnedReference
from shared.model_access.core_models import ScenarioNeed
from shared.model_access.reservation import (
    ModelLaunchScope,
    ModelWarmScope,
    SystemPreparationAuthority,
    WarmPreparationAuthority,
)

_SCENARIO_UNAVAILABLE = "allocation.scenario_unavailable"


def needs_model_preparation(request_id: UUID | str) -> bool:
    """Route lifecycle through the durable snapshot, not a mutable overlay alone."""
    from engine.services import get_model_launch_preparation

    if get_model_launch_preparation(UUID(str(request_id))) is not None:
        return True
    instance = RangeInstance.objects.filter(request__request_id=request_id).first()
    if instance is None:
        return False
    projection = project_scenario_model_needs(instance.scenario_id, expected_digest=instance.model_package_digest)
    if projection.resolution_failed:
        raise ContractError(_SCENARIO_UNAVAILABLE)
    return bool(projection.needs)


def _snapshot_needs(instance: RangeInstance) -> tuple[ScenarioNeed, ...]:
    """One package-bound identity controls both lifecycle routing and preparation."""
    from engine.services import get_model_launch_preparation

    assert instance.request is not None
    prepared = get_model_launch_preparation(instance.request.request_id)
    if prepared is not None:
        if any(need.scenario_digest != instance.model_package_digest for need in prepared.needs):
            raise ContractError(_SCENARIO_UNAVAILABLE)
        return prepared.needs
    projection = project_scenario_model_needs(instance.scenario_id, expected_digest=instance.model_package_digest)
    if projection.resolution_failed or (projection.needs and not projection.digest_verified):
        raise ContractError(_SCENARIO_UNAVAILABLE)
    return tuple(projection.needs.values())


def _warm_scope(instance: RangeInstance, deployment_id: UUID) -> ModelWarmScope | None:
    """Resolve warm authority only for generations without a user lease."""
    if instance.expires_at is not None:
        return None
    from engine.services import get_model_warm_scope

    assert instance.request is not None
    return get_model_warm_scope(instance.request.request_id, deployment_id=deployment_id)


def _standalone_scope(
    instance: RangeInstance,
    range_id: UUID,
    needs: tuple[ScenarioNeed, ...],
    deployment_id: UUID,
) -> ModelLaunchScope:
    """A non-event commitment uses the authored envelope and real lease window."""
    assert instance.request is not None
    warm = _warm_scope(instance, deployment_id)
    if instance.range_source == "ctf" or (instance.expires_at is None and warm is None):
        raise ContractError("allocation.scope_unavailable")
    if warm:
        kind: Literal["warm", "standalone"] = "warm"
        scope_id = warm.scope_id
        draw_key = warm.draw_key
        window_start = warm.window_start
        window_end = warm.window_end
        revisions = warm.authority_revisions
        system = WarmPreparationAuthority(
            owner_ref=OwnedReference(owner="management", reference=f"user:{instance.user_id}"),
            generation_id=warm.generation_id,
        )
    else:
        assert instance.expires_at is not None
        kind = "standalone"
        scope_id = draw_key = instance.request.request_id
        window_start = instance.created_at
        window_end = instance.expires_at
        revisions = ()
        system = None
    return ModelLaunchScope(
        kind=kind,
        scope_id=scope_id,
        draw_key=draw_key,
        subject_ref=OwnedReference(owner="deployment", reference=f"range:{range_id}"),
        window_start=window_start,
        window_end=window_end,
        authority_revisions=revisions,
        system_preparation=system,
        demands=tuple(
            EventModelDemand(
                workload_role=need.workload_role,
                expected_concurrency=1,
                per_participant_requests=need.limits.max_requests_per_window,
                per_participant_input_tokens=need.limits.max_input_tokens,
                per_participant_output_tokens=need.limits.max_output_tokens,
                allowed_strategy=need.allowed_strategies[0],
            )
            for need in needs
        ),
    )


def _resolve_model_catalog(
    request_id: UUID, owner: OwnedReference, needs: tuple[ScenarioNeed, ...]
) -> ModelAccessCatalog | None:
    """Return enabled policy or persist the permitted optional absence."""
    catalog = cast(ModelAccessCatalog | None, getattr(settings, "MODEL_ACCESS_CATALOG", None))
    if getattr(settings, "MODEL_ACCESS_ENABLED", False) and catalog is not None and catalog.enabled:
        return catalog
    if any(need.required for need in needs):
        raise ContractError("allocation.policy_unavailable")
    from engine.services import disable_optional_model_preparation

    disable_optional_model_preparation(request_id=request_id, owner_ref=owner, needs=needs)
    return None


def _authorize_preparation(
    instance: RangeInstance,
    owner: OwnedReference,
    system: SystemPreparationAuthority | WarmPreparationAuthority | None,
) -> None:
    """Authenticate active claimants or narrowly authorized inactive system owners."""
    from management.services import resolve_model_access_users, resolve_model_preparation_user
    from workspaces.services import WorkspaceOperation, authorize_launch_workspace_locked

    assert instance.request is not None
    actor = instance.request.user
    try:
        if system is None:
            resolve_model_access_users(actor, (instance.user_id,))
        elif (
            system.owner_ref != owner
            or actor.pk != instance.user_id
            or actor.is_active
            or actor.has_usable_password()
            or (system.kind == "warm_pool" and not actor.email.endswith("@warm-pool.invalid"))
        ):
            raise ContractError("allocation.system_owner_unavailable")
        else:
            resolve_model_preparation_user(instance.user_id)
        authorize_launch_workspace_locked(actor, instance.workspace_id, WorkspaceOperation.LAUNCH_RANGE)
    except Exception:
        raise ContractError("allocation.authority_unavailable") from None


def _source_policy_scope(instance: RangeInstance, scope: ModelLaunchScope) -> ModelLaunchScope:
    """Apply the range's current source-policy revision and optional sponsorship."""
    from shared.model_access.sources import ModelSourceSponsorship

    scope_updates: dict[str, object] = {"source_policy_revision": instance.model_source_policy_revision}
    if instance.model_source_sponsorship is not None:
        scope_updates["source_sponsorship"] = ModelSourceSponsorship.model_validate(instance.model_source_sponsorship)
    return scope.model_copy(update=scope_updates)


def _source_authority_refs(
    instance: RangeInstance, scope: ModelLaunchScope, refs: tuple[OwnedReference, ...], has_sources: bool
) -> tuple[OwnedReference, ...]:
    """Include sponsor or launch-tenant authority in the admission fence vector."""
    if scope.source_sponsorship:
        sponsor = OwnedReference(owner="management", reference=f"user:{scope.source_sponsorship.actor_id}")
        sponsor_workspace = OwnedReference(
            owner="workspaces", reference=f"workspace-id:{scope.source_sponsorship.workspace_id}"
        )
        sponsor_organization = OwnedReference(
            owner="workspaces", reference=f"organization:{scope.source_sponsorship.organization_uuid}"
        )
        refs = tuple(dict.fromkeys((*refs, sponsor, sponsor_workspace, sponsor_organization)))
    elif has_sources:
        if instance.request is None:
            raise ContractError("allocation.authority_unavailable")
        from workspaces.services import WorkspaceOperation, authorize_bound_workspace

        membership = authorize_bound_workspace(
            instance.request.user, instance.workspace_id, WorkspaceOperation.LAUNCH_RANGE
        )
        refs += (OwnedReference(owner="workspaces", reference=f"organization:{membership.organization_uuid}"),)
    return refs


def prepare_model_access_for_dispatch(request_id: UUID, *, range_id: UUID, renew: bool = False) -> None:
    """Authenticate current persisted ownership, then hand closed facts downward.

    Called after Range creation invalidates selectors and before enqueue, inside
    the same transaction. Missing policy, scope or authority denies required use.
    """
    from engine.services import get_model_launch_preparation, prepare_model_launch, project_model_launch_authority

    with transaction.atomic():
        instance = RangeInstance.objects.select_related("request__user").get(request__request_id=request_id)
        prepared = get_model_launch_preparation(request_id)
        needs = _snapshot_needs(instance)
        if not needs:
            return
        if prepared is not None and prepared.unavailable_reason and not renew:
            # The first operation's optional absence is immutable. A later
            # lifecycle generation may explicitly renew against current policy.
            return
        owner = OwnedReference(owner="management", reference=f"user:{instance.user_id}")
        catalog = _resolve_model_catalog(request_id, owner, needs)
        if catalog is None:
            return
        scope = (
            ModelLaunchScope.model_validate(instance.model_launch_scope)
            if instance.model_launch_scope
            else _standalone_scope(instance, range_id, needs, catalog.deployment_id)
        )

        scope = _source_policy_scope(instance, scope)
        system = scope.system_preparation
        _authorize_preparation(instance, owner, system)
        from cms.services._model_source_selection import resolve_launch_sources, resolve_sponsored_sources

        if scope.source_sponsorship:
            catalog, source_revisions = resolve_sponsored_sources(scope.source_sponsorship, catalog=catalog)
        else:
            catalog, source_revisions = resolve_launch_sources(
                instance.request.user,
                instance.workspace_id,
                instance.model_sources,
                catalog=catalog,
            )
        refs = (() if system else (owner,)) + (
            OwnedReference(owner="workspaces", reference=f"workspace-id:{instance.workspace_id}"),
            OwnedReference(owner="engine", reference=f"model-launch:{range_id}"),
        )
        refs = _source_authority_refs(instance, scope, refs, bool(source_revisions))
        from shared.model_access.projection_port import refresh_launch_projections

        refresh_launch_projections(catalog.deployment_id)
        revisions = project_model_launch_authority(deployment_id=catalog.deployment_id, authority_refs=refs)
        revisions += scope.authority_revisions + source_revisions
        prepare_model_launch(
            request_id=request_id,
            owner_ref=owner,
            needs=needs,
            scope=scope,
            authority_revisions=revisions,
            catalog=catalog,
            replace_revoked=renew,
        )


def resume_model_range(request_id: UUID) -> bool:
    """Join status transition, owner reauthorization and resumed launch atomically."""
    from engine.services import (
        dispatch_prepared_range_resume,
        get_authoritative_range_status,
        resolve_model_access_range_views,
        resume_range,
    )

    with transaction.atomic():
        if not resume_range(request_id, defer_dispatch=True):
            return False
        if get_authoritative_range_status(request_id=request_id) == "ready":
            return True
        (view,) = resolve_model_access_range_views(request_uuids=(request_id,))
        prepare_model_access_for_dispatch(request_id, range_id=view.range_uuid, renew=True)
        if not dispatch_prepared_range_resume(request_id):
            raise ContractError("allocation.dispatch_unavailable")
        return True
