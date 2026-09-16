"""Deterministic effective-policy compilation over overlapping sharing bindings (PLAT-202).

A range may simultaneously match deployment, user, group, event and explicit
range bindings. This module resolves that overlap into one canonically ordered
effective policy with full provenance, using a single implementation that
persistence, preview and later allocation all call rather than reproducing the
precedence rules in ORM queries, serializers or previews.

The compiler is pure and deterministic: its inputs are the pinned deployment and
catalog digest, an explicit evaluation instant, a canonical subject reference,
and the already-authorized binding/pool/profile projections plus their
membership revisions. It performs no ORM, HTTP, CTF/CMS or provider I/O, so it is
fully testable without a database.

Precedence (see ``docs/architecture/model-access/sharing.md``):

* Mandatory restrictions always apply and never yield to priority: capability,
  model and data-region allowlists intersect; deadlines and individual ceilings
  take their minima; every distinct budget/rate/concurrency/capacity account is
  enforced (identical references coalesce, never double-counted).
* Non-combinable choices - which provider pool supplies the subject, which
  routing affinity a logical alias uses - are resolved by the binding's explicit
  operator-controlled priority. Highest priority wins; identical values coalesce;
  equal priority with different values is an admission conflict and leaves the
  value unresolved. There is no priority-based bypass of a restriction or account.
* Unknown or stale membership fails closed: the whole result denies.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt

from shared.model_access.catalog import ContractError
from shared.model_access.core_models import (
    AccessLimits,
    AssignmentAffinity,
    ClosedModel,
    Digest,
    EffectiveProfile,
    Identifier,
    ModelProfile,
    OwnedReference,
    PositiveInt,
    SharingFacet,
)
from shared.model_access.sharing_models import SharingBinding, SharingPool


class BindingMatch(ClosedModel):
    """One already-authorized binding that applies to the subject being resolved."""

    binding: SharingBinding
    pool: SharingPool
    profile: ModelProfile | None = None
    membership_revision: PositiveInt
    membership_fresh: StrictBool
    matched_reason: Identifier


class PolicyContribution(ClosedModel):
    """What one matching binding contributed, for a complete provenance record."""

    sharing_binding_id: Identifier
    sharing_pool_id: Identifier
    definition_digest: Digest
    membership_revision: PositiveInt
    routing_revision: PositiveInt
    priority: Annotated[StrictInt, Field(ge=0, le=1000)]
    matched_reason: Identifier
    facets: tuple[SharingFacet, ...]


class PolicyConflict(ClosedModel):
    """A non-combinable choice or restriction that could not be resolved."""

    code: Annotated[str, Field(min_length=1, max_length=64)]
    facet: SharingFacet | None = None
    logical_alias: Identifier | None = None


class AliasRouting(ClosedModel):
    """The resolved per-alias routing choice, carrying the pool identity it maps to.

    The affinity alone is not the routing choice: two bindings that both assign an
    alias ``per_pool`` through *different* sharing pools are different choices with
    different allocation keys, and must conflict rather than coalesce. The pool id
    and routing revision are retained so allocation can reconstruct the key.
    """

    logical_alias: Identifier
    affinity: AssignmentAffinity
    sharing_pool_id: Identifier
    routing_revision: PositiveInt


class EffectivePolicy(ClosedModel):
    """The canonically ordered effective policy plus every contribution and conflict."""

    deployment_id: UUID
    catalog_digest: Digest
    evaluated_at: datetime
    subject: OwnedReference
    effective_profile: EffectiveProfile | None
    provider_pool_ref: Identifier | None
    capacity_account_refs: tuple[Identifier, ...]
    spend_account_refs: tuple[Identifier, ...]
    rate_account_refs: tuple[Identifier, ...]
    concurrency_account_refs: tuple[Identifier, ...]
    alias_routings: tuple[AliasRouting, ...]
    contributions: tuple[PolicyContribution, ...]
    conflicts: tuple[PolicyConflict, ...]
    stale: StrictBool

    @property
    def admissible(self) -> bool:
        """Whether this policy is safe to admit: no conflicts and no stale input."""
        return not self.stale and not self.conflicts


def compile_effective_policy(
    *,
    deployment_id: UUID,
    catalog_digest: Digest,
    evaluated_at: datetime,
    subject: OwnedReference,
    matches: tuple[BindingMatch, ...],
) -> EffectivePolicy:
    """Resolve overlapping matches into one deterministic effective policy."""
    ordered = _validated_order(deployment_id, matches)
    # Apply each binding's effective interval at the evaluation instant BEFORE
    # folding or checking freshness: a future or expired binding contributes no
    # accounts, restrictions or priority-winning choice.
    applicable = tuple(match for match in ordered if _within_interval(match, evaluated_at))
    contributions = tuple(_contribution(match) for match in applicable)

    if any(not match.membership_fresh for match in applicable):
        # Fail closed: an unknown or stale projection denies the whole result
        # rather than silently dropping a restriction it can no longer prove.
        return _denied(
            deployment_id,
            catalog_digest,
            evaluated_at,
            subject,
            contributions,
            (PolicyConflict(code="policy.stale_membership"),),
            stale=True,
        )

    conflicts: list[PolicyConflict] = []
    profile = _fold_profiles(applicable, conflicts)
    provider_pool_ref = _resolve_provider_pool(applicable, conflicts)
    alias_routings = _resolve_alias_routings(applicable, conflicts)

    return EffectivePolicy(
        deployment_id=deployment_id,
        catalog_digest=catalog_digest,
        evaluated_at=evaluated_at,
        subject=subject,
        effective_profile=profile,
        provider_pool_ref=provider_pool_ref,
        capacity_account_refs=_facet_accounts(applicable, SharingFacet.CAPACITY, _capacity_refs),
        spend_account_refs=_facet_accounts(applicable, SharingFacet.SPEND, lambda pool: pool.spend_account_refs),
        rate_account_refs=_facet_accounts(applicable, SharingFacet.RATE, lambda pool: pool.rate_account_refs),
        concurrency_account_refs=_facet_accounts(
            applicable, SharingFacet.CONCURRENCY, lambda pool: pool.concurrency_account_refs
        ),
        alias_routings=alias_routings,
        contributions=contributions,
        conflicts=tuple(conflicts),
        stale=False,
    )


def _within_interval(match: BindingMatch, evaluated_at: datetime) -> bool:
    """Whether the binding is effective at the evaluation instant, half-open [from, until)."""
    return match.binding.effective_from <= evaluated_at < match.binding.effective_until


def _validated_order(deployment_id: UUID, matches: tuple[BindingMatch, ...]) -> tuple[BindingMatch, ...]:
    """Reject foreign/inconsistent matches and order them canonically by binding id."""
    for match in matches:
        if match.binding.deployment_id != deployment_id:
            raise ContractError("policy.foreign_deployment", "matches.binding.deployment_id")
        if match.binding.sharing_pool_id != match.pool.sharing_pool_id:
            raise ContractError("policy.pool_mismatch", "matches.pool.sharing_pool_id")
        if SharingFacet.PROFILE in match.binding.facets and match.profile is None:
            raise ContractError("policy.missing_profile", "matches.profile")
    return tuple(sorted(matches, key=lambda match: match.binding.sharing_binding_id))


def _contribution(match: BindingMatch) -> PolicyContribution:
    """Build the provenance record for one matching binding."""
    return PolicyContribution(
        sharing_binding_id=match.binding.sharing_binding_id,
        sharing_pool_id=match.pool.sharing_pool_id,
        definition_digest=match.binding.definition_digest,
        membership_revision=match.membership_revision,
        routing_revision=match.pool.routing_revision,
        priority=match.binding.priority,
        matched_reason=match.matched_reason,
        facets=tuple(sorted(match.binding.facets, key=str)),
    )


def _capacity_refs(pool: SharingPool) -> tuple[str, ...]:
    """Return the pool's capacity account reference as a (possibly empty) set."""
    return (pool.capacity_account_ref,) if pool.capacity_account_ref is not None else ()


def _facet_accounts(
    matches: Sequence[BindingMatch],
    facet: SharingFacet,
    extract: Callable[[SharingPool], Sequence[str]],
) -> tuple[str, ...]:
    """Union the distinct account references contributed for one facet."""
    accounts: set[str] = set()
    for match in matches:
        if facet in match.binding.facets:
            accounts.update(extract(match.pool))
    return tuple(sorted(accounts))


def _resolve_provider_pool(matches: Sequence[BindingMatch], conflicts: list[PolicyConflict]) -> str | None:
    """Priority-resolve the single provider pool that supplies the subject."""
    candidates: list[tuple[int, str]] = []
    for match in matches:
        ref = match.pool.provider_pool_ref
        if SharingFacet.PROVIDER_IDENTITY in match.binding.facets and ref is not None:
            candidates.append((match.binding.priority, ref))
    value, conflicted = _resolve_single(candidates)
    if conflicted:
        conflicts.append(PolicyConflict(code="policy.provider_pool_conflict", facet=SharingFacet.PROVIDER_IDENTITY))
    return value


def _resolve_alias_routings(
    matches: Sequence[BindingMatch], conflicts: list[PolicyConflict]
) -> tuple[AliasRouting, ...]:
    """Priority-resolve the full per-alias routing choice (affinity + pool + revision).

    The choice value is the whole ``(affinity, pool, routing_revision)`` tuple, so
    two bindings that assign the same alias ``per_pool`` through different pools are
    a conflict rather than a coalesce, and the winning choice keeps its pool
    identity for the allocation key.
    """
    per_alias: dict[str, list[tuple[int, tuple[AssignmentAffinity, str, int]]]] = {}
    for match in matches:
        if SharingFacet.ROUTING in match.binding.facets:
            for alias_affinity in match.pool.alias_affinities:
                choice = (alias_affinity.affinity, match.pool.sharing_pool_id, match.pool.routing_revision)
                per_alias.setdefault(alias_affinity.logical_alias, []).append((match.binding.priority, choice))
    resolved: list[AliasRouting] = []
    for alias in sorted(per_alias):
        value, conflicted = _resolve_single(per_alias[alias])
        if conflicted:
            conflicts.append(
                PolicyConflict(code="policy.affinity_conflict", facet=SharingFacet.ROUTING, logical_alias=alias)
            )
        elif value is not None:
            affinity, pool_id, routing_revision = value
            resolved.append(
                AliasRouting(
                    logical_alias=alias,
                    affinity=affinity,
                    sharing_pool_id=pool_id,
                    routing_revision=routing_revision,
                )
            )
    return tuple(resolved)


def _resolve_single[Choice](candidates: Sequence[tuple[int, Choice]]) -> tuple[Choice | None, bool]:
    """Return the highest-priority value, or flag a conflict on an equal-priority tie."""
    if not candidates:
        return None, False
    top_priority = max(priority for priority, _ in candidates)
    top_values = {value for priority, value in candidates if priority == top_priority}
    if len(top_values) == 1:
        return next(iter(top_values)), False
    return None, True


def _fold_profiles(matches: Sequence[BindingMatch], conflicts: list[PolicyConflict]) -> EffectiveProfile | None:
    """Intersect every shared profile's allowlists and tighten every ceiling."""
    members: list[tuple[int, ModelProfile]] = []
    for match in matches:
        profile = match.profile
        if SharingFacet.PROFILE in match.binding.facets and profile is not None:
            members.append((match.binding.priority, profile))
    if not members:
        return None
    return _fold_valid_profiles(members, conflicts)


def _fold_valid_profiles(
    members: list[tuple[int, ModelProfile]], conflicts: list[PolicyConflict]
) -> EffectiveProfile | None:
    """Resolve the common profile id and fold the intersected, tightened profile."""
    profile_id, conflicted = _resolve_single([(priority, profile.profile_id) for priority, profile in members])
    if conflicted or profile_id is None:
        conflicts.append(PolicyConflict(code="policy.profile_conflict", facet=SharingFacet.PROFILE))
        return None

    profiles = [profile for _, profile in members]
    capabilities = _intersect(profile.capabilities for profile in profiles)
    data_regions = _intersect(profile.data_regions for profile in profiles)
    strategies = _intersect(profile.allowed_strategies for profile in profiles)
    limits = _fold_limits(profiles, conflicts)
    if not capabilities or not data_regions or not strategies or limits is None:
        conflicts.append(PolicyConflict(code="policy.empty_intersection", facet=SharingFacet.PROFILE))
        return None

    return EffectiveProfile(
        profile_id=profile_id,
        required=True,
        capabilities=tuple(sorted(capabilities, key=str)),
        allowed_strategies=tuple(sorted(strategies, key=str)),
        data_regions=tuple(sorted(data_regions, key=str)),
        limits=limits,
    )


def _intersect[T](collections: Iterable[Iterable[T]]) -> set[T]:
    """Intersect an iterable of collections into a single set (empty if none)."""
    sets = [set(collection) for collection in collections]
    if not sets:
        return set()
    result = sets[0]
    for other in sets[1:]:
        result = result & other
    return result


def _fold_limits(profiles: list[ModelProfile], conflicts: list[PolicyConflict]) -> AccessLimits | None:
    """Take the minimum of every ceiling, denying on a currency mismatch."""
    folded = profiles[0].limits
    for profile in profiles[1:]:
        try:
            folded = folded.tightened_with(profile.limits)
        except ValueError:
            conflicts.append(PolicyConflict(code="policy.currency_mismatch", facet=SharingFacet.PROFILE))
            return None
    return folded


def _denied(
    deployment_id: UUID,
    catalog_digest: Digest,
    evaluated_at: datetime,
    subject: OwnedReference,
    contributions: tuple[PolicyContribution, ...],
    conflicts: tuple[PolicyConflict, ...],
    *,
    stale: bool,
) -> EffectivePolicy:
    """Build a fail-closed effective policy that grants nothing."""
    return EffectivePolicy(
        deployment_id=deployment_id,
        catalog_digest=catalog_digest,
        evaluated_at=evaluated_at,
        subject=subject,
        effective_profile=None,
        provider_pool_ref=None,
        capacity_account_refs=(),
        spend_account_refs=(),
        rate_account_refs=(),
        concurrency_account_refs=(),
        alias_routings=(),
        contributions=contributions,
        conflicts=conflicts,
        stale=stale,
    )


__all__ = [
    "AliasRouting",
    "BindingMatch",
    "EffectivePolicy",
    "PolicyConflict",
    "PolicyContribution",
    "compile_effective_policy",
]
