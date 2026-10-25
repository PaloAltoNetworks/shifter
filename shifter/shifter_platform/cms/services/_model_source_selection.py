"""Resolve source choices under the launch workspace's actual tenant authority."""

from __future__ import annotations

from typing import TYPE_CHECKING, overload
from uuid import UUID

from shared.model_access import EventModelDemand, ModelAccessCatalog
from shared.model_access.reservation import AuthorityRevision
from shared.model_access.sources import ModelSourceSponsorship

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.scenarios.model_needs import ScenarioModelNeedsProjection
    from engine.services import ModelSourceView
    from shared.model_access.core_models import EffectiveProfile, ModelAlias
    from shared.model_access.sources import ModelSourceConfiguration

from engine.services import compile_authorized_model_sources, project_authorized_model_sources
from shared.model_access import ContractError
from shared.model_access.sources import ModelSourceSelection, ModelSourceUseScope
from workspaces.services import WorkspaceOperation, authorize_bound_workspace

SPONSOR_UNAVAILABLE = "source.sponsor_unavailable"


@overload
def resolve_launch_sources(
    actor: User, workspace_id: int, selection: object, *, catalog: ModelAccessCatalog
) -> tuple[ModelAccessCatalog, tuple[AuthorityRevision, ...]]:
    """Preserve the non-null catalog type when a deployment catalog is supplied."""
    ...


@overload
def resolve_launch_sources(
    actor: User, workspace_id: int, selection: object, *, catalog: None
) -> tuple[ModelAccessCatalog | None, tuple[AuthorityRevision, ...]]:
    """Preserve the optional catalog type when no deployment catalog is supplied."""
    ...


def resolve_launch_sources(
    actor: User, workspace_id: int, selection: object, *, catalog: ModelAccessCatalog | None
) -> tuple[ModelAccessCatalog | None, tuple[AuthorityRevision, ...]]:
    """Source selection conveys no permission to use another tenant's funds."""
    selected = ModelSourceSelection.model_validate(selection or {})
    if not selected.aliases:
        return catalog, ()
    if catalog is None or not catalog.enabled:
        raise ContractError("source.policy_unavailable")
    authorization = authorize_bound_workspace(actor, workspace_id, WorkspaceOperation.LAUNCH_RANGE)
    return resolve_model_source_selection(actor, authorization.organization_uuid, selected, catalog=catalog)


def resolve_model_source_sponsorship(
    actor: User, workspace_id: int, selection: object, *, administrative: bool = False
) -> ModelSourceSponsorship:
    """Validate an organizer's sources before projecting event sponsorship."""
    from django.conf import settings

    from shared.model_access.sources import ModelSourceSponsorship

    if administrative:
        from workspaces.services import authorize_model_source_workspace

        authorization = authorize_model_source_workspace(actor, workspace_id=workspace_id)
    else:
        authorization = authorize_bound_workspace(actor, workspace_id, WorkspaceOperation.USE_CTF_COMMUNICATIONS)
    catalog = getattr(settings, "MODEL_ACCESS_CATALOG", None)
    if not getattr(settings, "MODEL_ACCESS_ENABLED", False) or catalog is None:
        raise ContractError("source.policy_unavailable")
    if authorization.organization_uuid is None:
        raise ContractError(SPONSOR_UNAVAILABLE)
    selected = ModelSourceSelection.model_validate(selection)
    resolve_model_source_selection(actor, authorization.organization_uuid, selected, catalog=catalog)
    return ModelSourceSponsorship(
        actor_id=actor.pk,
        organization_uuid=authorization.organization_uuid,
        workspace_id=workspace_id,
        selection=selected,
        administrative=administrative,
    )


def resolve_sponsored_sources(
    sponsorship: ModelSourceSponsorship, *, catalog: ModelAccessCatalog
) -> tuple[ModelAccessCatalog, tuple[AuthorityRevision, ...]]:
    """Recheck persisted sponsor and tenant membership at participant admission."""
    from django.contrib.auth.models import User

    actor = User.objects.filter(pk=sponsorship.actor_id, is_active=True).first()
    if actor is None:
        raise ContractError(SPONSOR_UNAVAILABLE)
    current = resolve_model_source_sponsorship(
        actor, sponsorship.workspace_id, sponsorship.selection, administrative=sponsorship.administrative
    )
    if current != sponsorship:
        raise ContractError(SPONSOR_UNAVAILABLE)
    return resolve_model_source_selection(actor, sponsorship.organization_uuid, sponsorship.selection, catalog=catalog)


def _source_use_scope(actor: User, organization_uuid: UUID | None) -> ModelSourceUseScope:
    """Recheck active tenant membership before exposing source-use authority."""
    from django.contrib.auth.models import User

    from workspaces.services import OrganizationAuthorizationError, content_organization_uuids

    current = User.objects.filter(pk=actor.pk, is_active=True).first()
    if organization_uuid is None or organization_uuid not in content_organization_uuids(current):
        raise OrganizationAuthorizationError("Organization access denied")
    return ModelSourceUseScope(actor_id=actor.pk, organization_uuid=organization_uuid)


def list_usable_model_sources(actor: User, organization_uuid: UUID | None) -> tuple[ModelSourceView, ...]:
    """Resolve current tenancy before requesting runtime source metadata."""
    return project_authorized_model_sources(_source_use_scope(actor, organization_uuid))


def resolve_model_source_selection(
    actor: User, organization_uuid: UUID | None, selection: object, *, catalog: ModelAccessCatalog
) -> tuple[ModelAccessCatalog, tuple[AuthorityRevision, ...]]:
    """Compose tenancy authority with Engine-owned source grants and fences."""
    return compile_authorized_model_sources(_source_use_scope(actor, organization_uuid), selection, catalog=catalog)


def project_scenario_model_demands(scenario_id: str, *, expected_concurrency: int) -> tuple[EventModelDemand, ...]:
    """Use the verified authored envelope when an event has no demand override."""
    from cms.scenarios.model_needs import project_scenario_model_needs
    from shared.model_access import EventModelDemand

    projection = project_scenario_model_needs(scenario_id)
    if projection.resolution_failed or (projection.needs and not projection.digest_verified):
        raise ContractError("allocation.scenario_unavailable")
    return tuple(
        EventModelDemand(
            workload_role=need.workload_role,
            expected_concurrency=expected_concurrency,
            per_participant_requests=need.limits.max_requests_per_window,
            per_participant_input_tokens=need.limits.max_input_tokens,
            per_participant_output_tokens=need.limits.max_output_tokens,
            allowed_strategy=need.allowed_strategies[0],
        )
        for need in projection.needs.values()
    )


def model_source_alias_options(
    actor: User, organization: UUID | None, scenario: str
) -> tuple[list[dict[str, object]], bool]:
    """Project compatible authorized choices for the scenario's verified needs."""

    from django.conf import settings

    from cms.scenarios.model_needs import project_scenario_model_needs
    from cms.scenarios.registry import check_scenario_access

    catalog = getattr(settings, "MODEL_ACCESS_CATALOG", None)
    if not getattr(settings, "MODEL_ACCESS_ENABLED", False) or catalog is None:
        return [], False
    if not scenario:
        return [], True
    check_scenario_access(scenario, actor)
    projection = project_scenario_model_needs(scenario)
    if projection.resolution_failed or (projection.needs and not projection.digest_verified):
        raise ContractError("source.scenario_unavailable")
    sources = list_usable_model_sources(actor, organization)
    profiles = {need.profile_id for need in projection.needs.values()}
    aliases = []
    for alias in catalog.aliases:
        if alias.profile_id not in profiles:
            continue
        aliases.append(_alias_options(alias, catalog, projection, sources))
    return aliases, True


def _source_fits_alias(
    source: ModelSourceView, alias: ModelAlias, catalog: ModelAccessCatalog, projection: ScenarioModelNeedsProjection
) -> bool:
    """Check one candidate against authored regions, capabilities and counting bounds."""
    from shared.model_access.policy import intersect_profile
    from shared.model_access.source_catalog import compile_source_catalog
    from shared.model_access.sources import ModelSourceConfiguration

    selected = ModelSourceSelection.model_validate(
        {
            "aliases": [
                {
                    "logical_alias": alias.logical_alias,
                    "sources": [{"source_id": str(source.id), "revision": source.revision}],
                }
            ]
        }
    )
    try:
        config = ModelSourceConfiguration.model_validate(source.configuration)
        compiled = compile_source_catalog(catalog, selected, {source.id: (source.revision, config)})
        profile = next(item for item in compiled.profiles if item.profile_id == alias.profile_id)
        effective = [
            intersect_profile(profile, need)
            for need in projection.needs.values()
            if need.profile_id == alias.profile_id
        ]
        return all(_effective_source_fit(config, item) for item in effective)
    except (ContractError, ValueError):
        return False


def _alias_options(
    alias: ModelAlias,
    catalog: ModelAccessCatalog,
    projection: ScenarioModelNeedsProjection,
    sources: tuple[ModelSourceView, ...],
) -> dict[str, object]:
    """Expose compatible choices and the alias's effective mixing policy."""
    from dataclasses import asdict

    candidates = [asdict(source) for source in sources if _source_fits_alias(source, alias, catalog, projection)]
    profile = next(item for item in catalog.profiles if item.profile_id == alias.profile_id)
    multiple = "weighted-rendezvous-v1" in profile.allowed_strategies and all(
        "weighted-rendezvous-v1" in need.allowed_strategies
        for need in projection.needs.values()
        if need.profile_id == alias.profile_id
    )
    return {"logical_alias": alias.logical_alias, "multiple_allowed": multiple, "sources": candidates}


def _effective_source_fit(config: ModelSourceConfiguration, profile: EffectiveProfile | None) -> bool:
    """Check geography and the full-context reservation required without free counting."""
    if profile is None or config.region not in profile.data_regions:
        return False
    return config.provider != "openrouter-v1" or profile.limits.max_input_tokens >= config.context_window_tokens
