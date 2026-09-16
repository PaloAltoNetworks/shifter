"""Deterministic effective-policy compilation over overlapping bindings (PLAT-202)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from shared.model_access import AccessLimits, ContractError, ModelProfile, SelectorKind
from shared.model_access.core_models import AllocationStrategy, OwnedReference, SharingFacet
from shared.model_access.effective_policy import (
    AliasRouting,
    BindingMatch,
    EffectivePolicy,
    compile_effective_policy,
)
from shared.model_access.sharing_models import AliasAffinity, SharingBinding, SharingPool, SharingSelector

_DEPLOYMENT = UUID("11111111-1111-4111-8111-111111111111")
_OTHER_DEPLOYMENT = UUID("22222222-2222-4222-8222-222222222222")
_CATALOG_DIGEST = "sha256:" + "a" * 64
_EVAL = datetime(2026, 9, 15, tzinfo=UTC)
_FROM = datetime(2026, 9, 1, tzinfo=UTC)
_UNTIL = datetime(2026, 10, 1, tzinfo=UTC)
_SUBJECT = OwnedReference(owner="deployment", reference="range:r-1")


def _limits(**overrides) -> AccessLimits:
    values = {
        "max_request_seconds": 120,
        "max_request_bytes": 1_000_000,
        "max_input_tokens": 8_000,
        "max_output_tokens": 2_000,
        "max_requests_per_window": 60,
        "request_window_seconds": 60,
        "max_spend_micro_units": 5_000_000,
        "currency": "USD",
        "max_concurrent_requests": 4,
    }
    values.update(overrides)
    return AccessLimits.model_validate(values)


def _profile(
    profile_id: str = "coding",
    *,
    capabilities: tuple[str, ...] = ("messages", "token-count"),
    data_regions: tuple[str, ...] = ("europe-west4", "us-central1"),
    strategies: tuple[AllocationStrategy, ...] = (
        AllocationStrategy.FIXED_V1,
        AllocationStrategy.WEIGHTED_RENDEZVOUS_V1,
    ),
    limits: AccessLimits | None = None,
) -> ModelProfile:
    return ModelProfile(
        profile_id=profile_id,
        capabilities=capabilities,
        allowed_strategies=strategies,
        data_regions=data_regions,
        limits=limits or _limits(),
    )


def _pool(
    pool_id: str,
    *,
    routing_revision: int = 1,
    alias_affinities: tuple[AliasAffinity, ...] = (),
    provider_pool_ref: str | None = None,
    capacity_account_ref: str | None = None,
    spend: tuple[str, ...] = (),
    rate: tuple[str, ...] = (),
    concurrency: tuple[str, ...] = (),
) -> SharingPool:
    return SharingPool(
        sharing_pool_id=pool_id,
        routing_revision=routing_revision,
        alias_affinities=alias_affinities,
        provider_pool_ref=provider_pool_ref,
        capacity_account_ref=capacity_account_ref,
        spend_account_refs=spend,
        rate_account_refs=rate,
        concurrency_account_refs=concurrency,
    )


def _binding(
    binding_id: str,
    *,
    facets: tuple[SharingFacet, ...],
    pool_id: str,
    profile_id: str | None = None,
    priority: int = 0,
    deployment_id: UUID = _DEPLOYMENT,
) -> SharingBinding:
    return SharingBinding(
        contract_version="model-access-sharing/v1",
        sharing_binding_id=binding_id,
        deployment_id=deployment_id,
        selector=SharingSelector(kind=SelectorKind.ALL_RANGES),
        membership_mode="dynamic",
        membership_revision=1,
        authorized_publisher_ref=OwnedReference(owner="deployment", reference="operator:platform"),
        profile_id=profile_id,
        sharing_pool_id=pool_id,
        facets=facets,
        priority=priority,
        effective_from=_FROM,
        effective_until=_UNTIL,
        definition_digest="sha256:" + "0" * 64,
    )


def _match(
    binding: SharingBinding,
    pool: SharingPool,
    *,
    profile: ModelProfile | None = None,
    membership_revision: int = 1,
    fresh: bool = True,
    reason: str = "selected-ranges",
) -> BindingMatch:
    return BindingMatch(
        binding=binding,
        pool=pool,
        profile=profile,
        membership_revision=membership_revision,
        membership_fresh=fresh,
        matched_reason=reason,
    )


def _compile(matches: tuple[BindingMatch, ...]) -> EffectivePolicy:
    return compile_effective_policy(
        deployment_id=_DEPLOYMENT,
        catalog_digest=_CATALOG_DIGEST,
        evaluated_at=_EVAL,
        subject=_SUBJECT,
        matches=matches,
    )


def test_single_binding_contributes_its_facets_and_provenance():
    pool = _pool(
        "pool-a",
        spend=("acct-shared",),
        alias_affinities=(AliasAffinity(logical_alias="coding-main", affinity="per_pool"),),
    )
    binding = _binding("b-1", facets=(SharingFacet.SPEND, SharingFacet.ROUTING), pool_id="pool-a")
    policy = _compile((_match(binding, pool),))
    assert policy.spend_account_refs == ("acct-shared",)
    assert policy.alias_routings == (
        AliasRouting(logical_alias="coding-main", affinity="per_pool", sharing_pool_id="pool-a", routing_revision=1),
    )
    assert policy.conflicts == ()
    assert len(policy.contributions) == 1
    assert policy.contributions[0].sharing_binding_id == "b-1"
    assert set(policy.contributions[0].facets) == {SharingFacet.SPEND, SharingFacet.ROUTING}


def test_distinct_spend_accounts_union_and_identical_dedup():
    pool_a = _pool("pool-a", spend=("acct-shared", "acct-a"))
    pool_b = _pool("pool-b", spend=("acct-shared", "acct-b"))
    policy = _compile(
        (
            _match(_binding("b-1", facets=(SharingFacet.SPEND,), pool_id="pool-a"), pool_a),
            _match(_binding("b-2", facets=(SharingFacet.SPEND,), pool_id="pool-b"), pool_b),
        )
    )
    # Each distinct account applies exactly once; the shared one is not double-counted.
    assert policy.spend_account_refs == ("acct-a", "acct-b", "acct-shared")


def test_hard_restrictions_intersect_and_tighten():
    wide = _profile(
        capabilities=("messages", "token-count"),
        data_regions=("europe-west4", "us-central1"),
        limits=_limits(max_request_seconds=120, max_concurrent_requests=8),
    )
    tight = _profile(
        capabilities=("messages",),
        data_regions=("europe-west4",),
        limits=_limits(max_request_seconds=30, max_concurrent_requests=2),
    )
    policy = _compile(
        (
            _match(
                _binding("b-1", facets=(SharingFacet.PROFILE,), pool_id="pool-a", profile_id="coding"),
                _pool("pool-a", provider_pool_ref="provider-shared"),
                profile=wide,
            ),
            _match(
                _binding("b-2", facets=(SharingFacet.PROFILE,), pool_id="pool-b", profile_id="coding"),
                _pool("pool-b", provider_pool_ref="provider-shared"),
                profile=tight,
            ),
        )
    )
    assert policy.conflicts == ()
    assert policy.effective_profile is not None
    assert policy.effective_profile.capabilities == ("messages",)
    assert policy.effective_profile.data_regions == ("europe-west4",)
    assert policy.effective_profile.limits.max_request_seconds == 30
    assert policy.effective_profile.limits.max_concurrent_requests == 2


def test_priority_selects_non_combinable_provider_pool():
    low = _match(
        _binding("b-low", facets=(SharingFacet.PROVIDER_IDENTITY,), pool_id="pool-a", priority=10),
        _pool("pool-a", provider_pool_ref="provider-a"),
    )
    high = _match(
        _binding("b-high", facets=(SharingFacet.PROVIDER_IDENTITY,), pool_id="pool-b", priority=100),
        _pool("pool-b", provider_pool_ref="provider-b"),
    )
    policy = _compile((low, high))
    assert policy.provider_pool_ref == "provider-b"
    assert policy.conflicts == ()


def test_equal_priority_different_provider_pool_is_conflict():
    a = _match(
        _binding("b-a", facets=(SharingFacet.PROVIDER_IDENTITY,), pool_id="pool-a", priority=50),
        _pool("pool-a", provider_pool_ref="provider-a"),
    )
    b = _match(
        _binding("b-b", facets=(SharingFacet.PROVIDER_IDENTITY,), pool_id="pool-b", priority=50),
        _pool("pool-b", provider_pool_ref="provider-b"),
    )
    policy = _compile((a, b))
    assert policy.provider_pool_ref is None
    assert any(c.facet is SharingFacet.PROVIDER_IDENTITY for c in policy.conflicts)


def test_identical_non_combinable_values_coalesce():
    a = _match(
        _binding("b-a", facets=(SharingFacet.PROVIDER_IDENTITY,), pool_id="pool-a", priority=50),
        _pool("pool-a", provider_pool_ref="provider-x"),
    )
    b = _match(
        _binding("b-b", facets=(SharingFacet.PROVIDER_IDENTITY,), pool_id="pool-b", priority=50),
        _pool("pool-b", provider_pool_ref="provider-x"),
    )
    policy = _compile((a, b))
    assert policy.provider_pool_ref == "provider-x"
    assert policy.conflicts == ()


def test_priority_cannot_drop_a_lower_priority_account_or_loosen_a_cap():
    # High-priority binding shares spend acct-a with a loose cap; low-priority shares acct-b with a tight cap.
    high = _match(
        _binding(
            "b-high",
            facets=(SharingFacet.PROFILE, SharingFacet.SPEND),
            pool_id="pool-a",
            profile_id="coding",
            priority=100,
        ),
        _pool("pool-a", spend=("acct-a",)),
        profile=_profile(limits=_limits(max_spend_micro_units=9_000_000)),
    )
    low = _match(
        _binding(
            "b-low",
            facets=(SharingFacet.PROFILE, SharingFacet.SPEND),
            pool_id="pool-b",
            profile_id="coding",
            priority=1,
        ),
        _pool("pool-b", spend=("acct-b",)),
        profile=_profile(limits=_limits(max_spend_micro_units=1_000_000)),
    )
    policy = _compile((high, low))
    # Distinct accounts both enforced regardless of priority.
    assert policy.spend_account_refs == ("acct-a", "acct-b")
    # The tighter cap wins even though it came from the lower-priority binding.
    assert policy.effective_profile.limits.max_spend_micro_units == 1_000_000


def test_stale_membership_fails_closed():
    pool = _pool("pool-a", spend=("acct-a",))
    policy = _compile((_match(_binding("b-1", facets=(SharingFacet.SPEND,), pool_id="pool-a"), pool, fresh=False),))
    assert policy.stale is True
    assert policy.effective_profile is None
    assert policy.spend_account_refs == ()
    assert any(c.code == "policy.stale_membership" for c in policy.conflicts)


def test_empty_capability_intersection_denies_profile():
    a = _match(
        _binding("b-a", facets=(SharingFacet.PROFILE,), pool_id="pool-a", profile_id="coding"),
        _pool("pool-a", provider_pool_ref="provider-shared"),
        profile=_profile(capabilities=("messages",)),
    )
    b = _match(
        _binding("b-b", facets=(SharingFacet.PROFILE,), pool_id="pool-b", profile_id="coding"),
        _pool("pool-b", provider_pool_ref="provider-shared"),
        profile=_profile(capabilities=("token-count",)),
    )
    policy = _compile((a, b))
    assert policy.effective_profile is None
    assert any(c.facet is SharingFacet.PROFILE for c in policy.conflicts)


def test_per_alias_affinity_conflict_on_equal_priority():
    a = _match(
        _binding("b-a", facets=(SharingFacet.ROUTING,), pool_id="pool-a", priority=5),
        _pool("pool-a", alias_affinities=(AliasAffinity(logical_alias="coding-main", affinity="per_user"),)),
    )
    b = _match(
        _binding("b-b", facets=(SharingFacet.ROUTING,), pool_id="pool-b", priority=5),
        _pool("pool-b", alias_affinities=(AliasAffinity(logical_alias="coding-main", affinity="per_pool"),)),
    )
    policy = _compile((a, b))
    assert policy.alias_routings == ()
    assert any(c.facet is SharingFacet.ROUTING and c.logical_alias == "coding-main" for c in policy.conflicts)


def test_equal_priority_same_affinity_through_different_pools_conflicts():
    # Both assign coding-main per_pool, but through DISTINCT pools: different
    # allocation identity, so they must conflict rather than silently coalesce.
    a = _match(
        _binding("b-a", facets=(SharingFacet.ROUTING,), pool_id="pool-a", priority=7),
        _pool("pool-a", alias_affinities=(AliasAffinity(logical_alias="coding-main", affinity="per_pool"),)),
    )
    b = _match(
        _binding("b-b", facets=(SharingFacet.ROUTING,), pool_id="pool-b", priority=7),
        _pool("pool-b", alias_affinities=(AliasAffinity(logical_alias="coding-main", affinity="per_pool"),)),
    )
    policy = _compile((a, b))
    assert policy.alias_routings == ()
    assert any(c.facet is SharingFacet.ROUTING and c.logical_alias == "coding-main" for c in policy.conflicts)


def test_winning_routing_choice_retains_its_pool_and_revision():
    low = _match(
        _binding("b-low", facets=(SharingFacet.ROUTING,), pool_id="pool-a", priority=1),
        _pool(
            "pool-a",
            routing_revision=1,
            alias_affinities=(AliasAffinity(logical_alias="coding-main", affinity="per_user"),),
        ),
    )
    high = _match(
        _binding("b-high", facets=(SharingFacet.ROUTING,), pool_id="pool-b", priority=9),
        _pool(
            "pool-b",
            routing_revision=4,
            alias_affinities=(AliasAffinity(logical_alias="coding-main", affinity="per_pool"),),
        ),
    )
    policy = _compile((low, high))
    assert policy.alias_routings == (
        AliasRouting(logical_alias="coding-main", affinity="per_pool", sharing_pool_id="pool-b", routing_revision=4),
    )
    assert policy.conflicts == ()


def test_result_is_deterministic_under_input_reordering():
    pool_a = _pool("pool-a", spend=("acct-a",))
    pool_b = _pool("pool-b", spend=("acct-b",))
    m_a = _match(_binding("b-a", facets=(SharingFacet.SPEND,), pool_id="pool-a"), pool_a)
    m_b = _match(_binding("b-b", facets=(SharingFacet.SPEND,), pool_id="pool-b"), pool_b)
    forward = _compile((m_a, m_b))
    reverse = _compile((m_b, m_a))
    assert forward == reverse


def test_foreign_deployment_binding_is_rejected():
    pool = _pool("pool-a", spend=("acct-a",))
    foreign = _binding("b-foreign", facets=(SharingFacet.SPEND,), pool_id="pool-a", deployment_id=_OTHER_DEPLOYMENT)
    match = _match(foreign, pool)
    with pytest.raises(ContractError) as exc:
        _compile((match,))
    assert exc.value.code == "policy.foreign_deployment"


def test_no_matches_denies_by_default_without_unlimited_access():
    policy = _compile(())
    assert policy.effective_profile is None
    assert policy.spend_account_refs == ()
    assert policy.provider_pool_ref is None
    assert policy.contributions == ()


def test_bindings_outside_effective_interval_do_not_contribute():
    pool = _pool("pool-a", spend=("acct-a",))
    match = _match(_binding("b-1", facets=(SharingFacet.SPEND,), pool_id="pool-a"), pool)

    def _compile_at(instant):
        return compile_effective_policy(
            deployment_id=_DEPLOYMENT,
            catalog_digest=_CATALOG_DIGEST,
            evaluated_at=instant,
            subject=_SUBJECT,
            matches=(match,),
        )

    before = _compile_at(datetime(2026, 8, 1, tzinfo=UTC))
    active = _compile_at(datetime(2026, 9, 15, tzinfo=UTC))
    expired = _compile_at(datetime(2026, 10, 2, tzinfo=UTC))

    assert before.contributions == ()
    assert before.spend_account_refs == ()
    assert active.spend_account_refs == ("acct-a",)
    assert len(active.contributions) == 1
    assert expired.contributions == ()
