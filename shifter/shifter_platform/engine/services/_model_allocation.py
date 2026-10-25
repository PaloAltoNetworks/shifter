"""Atomic model quota allocation, pinned routing and non-usable grant bindings."""

import logging
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from engine.models import (
    AllocationGroup,
    ModelAliasAssignment,
    ModelAllocation,
    ModelAllocationAuthority,
    ModelPendingGrant,
    ModelQuotaIdentity,
    Range,
    SharingAuthorityFence,
)
from shared.model_access import ContractError, ModelAccessCatalog, compute_digest, validate_catalog
from shared.model_access.core_models import EffectiveProfile, ModelAlias, ModelShard, PriceSchedule
from shared.model_access.effective_policy import EffectivePolicy
from shared.model_access.policy import intersect_profile
from shared.model_access.reservation import ModelAllocationRequest, ModelQuotaObservation

from ._model_allocation_authority import lock_assignment_groups, locked_policy
from ._model_allocation_contracts import normalize_observations, validated
from ._model_allocation_selection import _eligible, _policy_digest, _provider_candidates, _rank
from ._model_cohort_capacity import cohort_commitments
from ._model_quota import QuotaAdmissionState, add_shard_demand, lock_quotas, persist_draws, vector_fits

logger = logging.getLogger(__name__)


def _lock_range(request: ModelAllocationRequest) -> Range:
    """Lock and authenticate the exact range generation being admitted."""
    row = (
        Range.objects.select_for_update().filter(uuid=request.range_id, request__request_id=request.request_id).first()
    )
    if row is None or row.provisioner_operation_id != request.operation_id:
        raise ContractError("allocation.generation_mismatch")
    if row.model_source_policy_revision != request.source_policy_revision:
        raise ContractError("allocation.policy_revision_mismatch")
    if request.owner_ref.owner != "management" or request.owner_ref.reference != f"user:{row.user_id}":
        raise ContractError("allocation.owner_mismatch")
    if row.status not in (Range.Status.PENDING, Range.Status.PROVISIONING, Range.Status.READY, Range.Status.RESUMING):
        raise ContractError("allocation.range_unavailable")
    if row.egress_mode in {"none", "deny-all"}:
        raise ContractError("allocation.egress_incompatible")
    if request.preparation_authority is not None and row.provisioner_operation != "raes-range:provision":
        raise ContractError("allocation.system_preparation_only")
    return row


def _replay(request: ModelAllocationRequest, intent_digest: str) -> ModelAllocation | None:
    """Return an identical live admission or reject a conflicting replay."""
    existing = ModelAllocation.objects.filter(
        request_id=request.request_id,
        operation_id=request.operation_id,
        workload_role=request.need.workload_role,
        source_policy_revision=request.source_policy_revision,
    ).first()
    if existing is None:
        return None
    if existing.intent_digest != intent_digest:
        raise ContractError("allocation.intent_conflict")
    if (
        existing.released_at is not None
        or existing.grant.state not in {"pending", "active"}
        or timezone.now() >= existing.deadline
    ):
        raise ContractError("allocation.revoked")
    return existing


def _effective_profile(
    request: ModelAllocationRequest, catalog: ModelAccessCatalog, sharing: EffectivePolicy
) -> EffectiveProfile:
    """Intersect authored need with catalog and incumbent sharing policy."""
    profile = next((item for item in catalog.profiles if item.profile_id == request.need.profile_id), None)
    if profile is None or not catalog.enabled or not sharing.admissible:
        raise ContractError("allocation.policy_unavailable")
    effective = intersect_profile(profile, request.need)
    if effective is None:
        raise ContractError("allocation.policy_unavailable")
    if sharing.effective_profile is not None:
        other = sharing.effective_profile
        effective = effective.model_copy(
            update={
                "capabilities": tuple(sorted(set(effective.capabilities) & set(other.capabilities))),
                "data_regions": tuple(sorted(set(effective.data_regions) & set(other.data_regions))),
                "allowed_strategies": tuple(sorted(set(effective.allowed_strategies) & set(other.allowed_strategies))),
                "limits": effective.limits.tightened_with(other.limits),
            }
        )
    if not set(request.need.required_capabilities).issubset(effective.capabilities):
        raise ContractError("allocation.capability_unavailable")
    if request.demand.allowed_strategy not in effective.allowed_strategies:
        raise ContractError("allocation.strategy_not_allowed")
    return effective


@dataclass(frozen=True)
class _SelectionContext:
    """Immutable routing and capacity inputs shared across alias choices."""

    request: ModelAllocationRequest
    catalog: ModelAccessCatalog
    sharing: EffectivePolicy
    profile: EffectiveProfile
    locked: dict[str, ModelQuotaIdentity]
    observations: dict[str, ModelQuotaObservation]
    groups: dict[str, AllocationGroup]
    policy_digest: str
    prices: dict[str, PriceSchedule]
    allowed_shards: set[str]
    commitments: dict[str, int] | None


def _alias_candidates(
    alias: ModelAlias,
    context: _SelectionContext,
    group: AllocationGroup | None,
    assignment: ModelAliasAssignment | None,
) -> list[ModelShard]:
    """Apply provider-pool and any prior shared assignment constraints."""
    candidates = [
        shard
        for shard in _rank(alias, context.request, context.catalog, context.policy_digest, group)
        if shard.shard_id in context.allowed_shards
    ]
    if assignment is None:
        return candidates
    candidates = [shard for shard in candidates if shard.model_dump(mode="json") == assignment.shard]
    if not candidates or not _eligible(candidates[0], context.profile, context.observations, timezone.now()):
        raise ContractError("allocation.shared_assignment_incompatible")
    return candidates


def _candidate_vector(shard: ModelShard, vector: dict[str, int], context: _SelectionContext) -> dict[str, int] | None:
    """Return the feasible demand vector for one healthy candidate."""
    if not _eligible(shard, context.profile, context.observations, timezone.now()):
        return None
    candidate = add_shard_demand(vector, shard, context.catalog, context.request.demand)
    if not vector_fits(
        candidate,
        request=context.request,
        effective=context.sharing,
        catalog=context.catalog,
        locked=context.locked,
        observations=context.observations,
        commitments=context.commitments,
    ):
        return None
    return candidate


def _persist_group_assignment(
    *,
    group: AllocationGroup | None,
    assignment: ModelAliasAssignment | None,
    alias: ModelAlias,
    shard: ModelShard,
    policy_digest: str,
) -> None:
    """Pin the first shared alias choice after it passes capacity checks."""
    if group is not None and assignment is None:
        ModelAliasAssignment.objects.create(
            group=group,
            logical_alias=alias.logical_alias,
            shard=shard.model_dump(mode="json"),
            policy_digest=policy_digest,
        )


def _select_alias(
    alias: ModelAlias, vector: dict[str, int], context: _SelectionContext
) -> tuple[ModelShard, dict[str, int]]:
    """Choose one alias without exposing a partial persisted assignment."""
    if alias.strategy not in context.profile.allowed_strategies:
        raise ContractError("allocation.strategy_not_allowed")
    group = context.groups.get(alias.logical_alias)
    assignment = (
        ModelAliasAssignment.objects.filter(group=group, logical_alias=alias.logical_alias).first() if group else None
    )
    priced_candidate = False
    for shard in _alias_candidates(alias, context, group, assignment):
        price = context.catalog.price_for_alias(alias.logical_alias, shard.shard_id)
        if price.valid_until < context.request.window_end or price.currency != context.profile.limits.currency:
            continue
        priced_candidate = True
        candidate = _candidate_vector(shard, vector, context)
        if candidate is None:
            continue
        _persist_group_assignment(
            group=group,
            assignment=assignment,
            alias=alias,
            shard=shard,
            policy_digest=context.policy_digest,
        )
        return shard, candidate
    raise ContractError("allocation.capacity_unavailable" if priced_candidate else "allocation.price_unavailable")


def _select(
    request: ModelAllocationRequest,
    catalog: ModelAccessCatalog,
    sharing: EffectivePolicy,
    profile: EffectiveProfile,
    quota: QuotaAdmissionState,
    groups: dict[str, AllocationGroup],
    commitments: dict[str, int] | None,
) -> tuple[dict[str, ModelShard], dict[str, int]]:
    """Choose a complete feasible alias map without partial effects."""
    policy_digest = _policy_digest(request, catalog, profile)
    selected: dict[str, ModelShard] = {}
    vector: dict[str, int] = {}
    aliases = [alias for alias in catalog.aliases if alias.profile_id == request.need.profile_id]
    if not aliases:
        raise ContractError("allocation.alias_unavailable")
    prices = {price.price_schedule_id: price for price in catalog.price_schedules}
    allowed_shards = _provider_candidates(catalog, sharing)
    context = _SelectionContext(
        request=request,
        catalog=catalog,
        sharing=sharing,
        profile=profile,
        locked=quota.locked,
        observations=quota.observations,
        groups=groups,
        policy_digest=policy_digest,
        prices=prices,
        allowed_shards=allowed_shards,
        commitments=commitments,
    )
    for alias in aliases:
        selected[alias.logical_alias], vector = _select_alias(alias, vector, context)
    return selected, vector


def allocate_model_access(
    request: ModelAllocationRequest,
    *,
    catalog: ModelAccessCatalog,
    observations: tuple[object, ...],
    retire_previous: bool = False,
) -> ModelAllocation:
    """Record bounded admission timing without provider, prompt or identity labels."""
    started = perf_counter()
    try:
        allocation = _allocate_model_access(
            request, catalog=catalog, observations=observations, retire_previous=retire_previous
        )
    except ContractError:
        _admission_metric("denied", started)
        raise
    transaction.on_commit(lambda: _admission_metric("admitted", started))
    return allocation


def _admission_metric(outcome: str, started: float) -> None:
    """Use the existing structured logging transport; no network in the transaction."""
    logger.info(
        "model-access allocation",
        extra={
            "model_access_namespace": "Shifter/ModelAccess",
            "model_access_outcome": outcome,
            "model_access_elapsed_ms": (perf_counter() - started) * 1000,
        },
    )


def _previous_allocations(
    request: ModelAllocationRequest, retire_previous: bool
) -> tuple[list[ModelAllocation], set[str]]:
    """Find replaceable generations and every quota mutex they still use."""
    previous = (
        list(
            ModelAllocation.objects.filter(range_id=request.range_id, released_at__isnull=True).exclude(
                operation_id=request.operation_id, source_policy_revision=request.source_policy_revision
            )
        )
        if retire_previous
        else []
    )
    quota_ids = {
        quota_id for prior in previous for quota_id in prior.draws.values_list("reservation__quota_id", flat=True)
    }
    return previous, quota_ids


@dataclass(frozen=True)
class _CommitContext:
    """Complete locked inputs for the final recheck and atomic effects."""

    request: ModelAllocationRequest
    range_obj: Range
    catalog: ModelAccessCatalog
    sharing: EffectivePolicy
    profile: EffectiveProfile
    locked: dict[str, ModelQuotaIdentity]
    observed: dict[str, ModelQuotaObservation]
    fences: list[SharingAuthorityFence]
    revision_vector: dict[str, object]
    selected: dict[str, ModelShard]
    vector: dict[str, int]
    commitments: dict[str, int] | None
    intent_digest: str
    policy_digest: str


def _assert_current(context: _CommitContext) -> None:
    """Recheck time, health, and headroom after every potentially waiting lock."""
    now = timezone.now()
    if now >= datetime.fromisoformat(str(context.revision_vector["fresh_until"])):
        raise ContractError("allocation.authority_unavailable")
    shards_healthy = all(
        _eligible(shard, context.profile, context.observed, now) for shard in context.selected.values()
    )
    capacity_available = vector_fits(
        context.vector,
        request=context.request,
        effective=context.sharing,
        catalog=context.catalog,
        locked=context.locked,
        observations=context.observed,
        commitments=context.commitments,
    )
    if not shards_healthy or not capacity_available:
        raise ContractError("allocation.capacity_unavailable")


def _persist_allocation(context: _CommitContext) -> ModelAllocation:
    """Write the allocation, pending grant, authority pins, and exact draws."""
    request = context.request
    allocation = ModelAllocation.objects.create(
        deployment_id=request.deployment_id,
        request_id=request.request_id,
        operation_id=request.operation_id,
        range_id=request.range_id,
        draw_key=request.draw_key,
        workload_role=request.need.workload_role,
        source_policy_revision=request.source_policy_revision,
        intent_digest=context.intent_digest,
        policy_digest=context.policy_digest,
        # The credential lifetime is the range session window, not the membership
        # freshness window. Membership freshness (revision_vector["fresh_until"],
        # ~5 min) is a re-validation interval, not a hard cap: owner revocations are
        # caught synchronously on every exchange/refresh/authenticate by the
        # authority-fence pins (_recheck_authority), and each rotation additionally
        # re-derives the effective policy from the current projection
        # (_revalidate_membership). Capping the credential at fresh_until killed any
        # provision or session that outlasted the freshness window (e.g. GCE range
        # boot, which exceeds 5 minutes). See ADR-064 and _revalidate_membership.
        deadline=request.window_end,
        alias_shards={alias: shard.shard_id for alias, shard in context.selected.items()},
        snapshot={
            "request": request.model_dump(mode="json"),
            "need": request.need.model_dump(mode="json"),
            "catalog": context.catalog.model_dump(mode="json"),
            "effective_policy": context.sharing.model_dump(mode="json"),
            "profile": context.profile.model_dump(mode="json"),
            "revision_vector": context.revision_vector,
            "shards": {alias: shard.model_dump(mode="json") for alias, shard in context.selected.items()},
        },
    )
    previous_epoch = (
        ModelPendingGrant.objects.filter(allocation__range_id=request.range_id).aggregate(maximum=Max("grant_epoch"))[
            "maximum"
        ]
        or 0
    )
    ModelPendingGrant.objects.create(allocation=allocation, grant_epoch=previous_epoch + 1)
    ModelAllocationAuthority.objects.bulk_create(
        ModelAllocationAuthority(allocation=allocation, fence=fence, revision=fence.authority_revision)
        for fence in context.fences
    )
    persist_draws(
        allocation,
        context.vector,
        request=request,
        effective=context.sharing,
        catalog=context.catalog,
        quota=QuotaAdmissionState(context.locked, context.observed),
        commitments=context.commitments,
    )
    from shared.audit import AuditActorType, AuditEvent, audit_log

    audit_log(
        AuditEvent(
            entity_type="range",
            entity_id=context.range_obj.pk,
            action="capacity_assess",
            actor_type=AuditActorType.SYSTEM,
            context=f"model-access allocation={allocation.pk} operation={request.operation_id}",
        ),
        strict=True,
    )
    return allocation


def _allocate_model_access(
    request: ModelAllocationRequest,
    *,
    catalog: ModelAccessCatalog,
    observations: tuple[object, ...],
    retire_previous: bool = False,
) -> ModelAllocation:
    """Commit all alias effects or none; caller may join the launch transaction."""
    request = validated(ModelAllocationRequest, request)
    observed = normalize_observations(observations)
    intent_digest = compute_digest(request)
    with transaction.atomic():
        range_obj = _lock_range(request)
        existing = _replay(request, intent_digest)
        pinned_catalog = (
            validate_catalog(existing.snapshot["catalog"])
            if existing
            else validate_catalog(catalog.model_dump(mode="json"))
        )
        sharing, fences, revision_vector = locked_policy(request, pinned_catalog)
        if existing is not None:
            if existing.snapshot["revision_vector"] != revision_vector:
                raise ContractError("allocation.authority_changed")
            return existing
        catalog = pinned_catalog
        if catalog.deployment_id != request.deployment_id:
            raise ContractError("allocation.deployment_mismatch")
        profile = _effective_profile(request, catalog, sharing)
        policy_digest = _policy_digest(request, catalog, profile)
        groups = lock_assignment_groups(request, catalog, sharing)
        previous, old_quotas = _previous_allocations(request, retire_previous)
        locked = lock_quotas(catalog, request.need.profile_id, _provider_candidates(catalog, sharing), old_quotas)
        from ._model_allocation_lifecycle import release_model_allocation

        for prior in previous:
            release_model_allocation(prior.pk, operation_id=prior.operation_id)
        commitments = cohort_commitments(request, catalog, sharing, profile, observed, groups)
        selected, vector = _select(
            request, catalog, sharing, profile, QuotaAdmissionState(locked, observed), groups, commitments
        )
        context = _CommitContext(
            request=request,
            range_obj=range_obj,
            catalog=catalog,
            sharing=sharing,
            profile=profile,
            locked=locked,
            observed=observed,
            fences=fences,
            revision_vector=revision_vector,
            selected=selected,
            vector=vector,
            commitments=commitments,
            intent_digest=intent_digest,
            policy_digest=policy_digest,
        )
        _assert_current(context)
        return _persist_allocation(context)
