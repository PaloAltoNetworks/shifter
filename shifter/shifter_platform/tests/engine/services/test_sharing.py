"""Engine-owned sharing binding persistence, facades, and fencing (PLAT-202, M19).

Exercises immutable published revisions with a pinned catalog and profile,
optimistic revision fencing, membership-evidence requirements and freshness,
frozen snapshot membership, effective intervals, withdrawal tombstoning and
stable allocation-group identity through a real database. These run in the
SQLite coverage lane and again on real PostgreSQL in the semantics lane, so the
constraint/fencing behavior is proven against actual PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, timedelta
from uuid import UUID

import pytest
from django.utils import timezone

from shared.model_access import (
    PublisherAuthorityScope,
    SharingAuthorityEvidence,
    compute_digest,
    seal_catalog,
    seal_sharing_binding,
)
from shared.model_access.core_models import SelectorKind, SharingFacet
from shared.model_access.sharing_models import SharingSelector

pytestmark = [pytest.mark.django_db(transaction=True)]

_DEPLOYMENT = UUID("11111111-1111-4111-8111-111111111111")
_OTHER_DEPLOYMENT = UUID("22222222-2222-4222-8222-222222222222")
_PUBLISHER = {"owner": "deployment", "reference": "operator:platform"}
_SUBJECT = {"owner": "deployment", "reference": "range:r-1"}
_FROM = "2026-09-01T00:00:00Z"
_UNTIL = "2026-10-01T00:00:00Z"
_ALL_RANGES_DIGEST = compute_digest(SharingSelector(kind=SelectorKind.ALL_RANGES))


def _limits(spend_cap: int = 5_000_000) -> dict:
    return {
        "max_request_seconds": 120,
        "max_request_bytes": 1_000_000,
        "max_input_tokens": 8_000,
        "max_output_tokens": 2_000,
        "max_requests_per_window": 60,
        "request_window_seconds": 60,
        "max_spend_micro_units": spend_cap,
        "currency": "USD",
        "max_concurrent_requests": 4,
    }


def _catalog(deployment_id: UUID = _DEPLOYMENT, *, spend_cap: int = 5_000_000):
    payload = {
        "contract_version": "model-access-policy/v1",
        "deployment_id": str(deployment_id),
        "enabled": False,
        "profiles": [
            {
                "profile_id": "coding",
                "capabilities": ["messages", "token-count"],
                "allowed_strategies": ["fixed-v1", "weighted-rendezvous-v1"],
                "data_regions": ["europe-west4"],
                "limits": _limits(spend_cap),
            }
        ],
        "quota_pools": [
            {
                "quota_pool_id": "vertex-tokens-eu",
                "provider_adapter_id": "vertex-v1",
                "provider_quota_identity": "project:models-a/region:europe-west4/model:claude",
                "dimension": "input_tokens",
                "unit": "tokens/minute",
                "limit": 1000000,
            }
        ],
        "price_schedules": [
            {
                "price_schedule_id": "vertex-2026-09",
                "currency": "USD",
                "valid_until": "2026-10-01T00:00:00Z",
                "prices": [{"component": "input_tokens", "unit_denominator": 1000000, "price_micro_units": 3000000}],
            }
        ],
        "shards": [
            {
                "shard_id": "vertex-primary",
                "provider_adapter_id": "vertex-v1",
                "compute_target_ref": {"owner": "installation", "reference": "gcp:gce-primary"},
                "model_project_ref": {"owner": "deployment", "reference": "project:models-a"},
                "model_account_ref": {"owner": "deployment", "reference": "billing:models-a"},
                "dynamic_secret_project_ref": {"owner": "deployment", "reference": "project:secrets-a"},
                "broker_workload_identity_ref": {"owner": "deployment", "reference": "gsa:model-broker"},
                "credential_ref": {"owner": "broker", "reference": "impersonate:gsa/model-invoke"},
                "region": "europe-west4",
                "provider_model": "publishers/anthropic/models/claude-sonnet",
                "provider_model_version": "20260901",
                "protocol": "anthropic-messages/2023-06-01",
                "capabilities": ["messages", "token-count"],
                "billing_components": ["input_tokens"],
                "quota_pool_ids": ["vertex-tokens-eu"],
                "weight": 1,
                "enabled": True,
            }
        ],
        "aliases": [
            {
                "logical_alias": "coding-main",
                "profile_id": "coding",
                "strategy": "fixed-v1",
                "affinity": "per_range",
                "eligible_shard_ids": ["vertex-primary"],
                "price_schedule_id": "vertex-2026-09",
            }
        ],
        "sharing_pools": [],
        "sharing_bindings": [],
    }
    return seal_catalog(payload)


def _pool_dto(
    pool_id="pool-a",
    *,
    routing_revision=1,
    alias_affinities=(("coding-main", "per_pool"),),
    spend=("acct-shared",),
    provider_pool_ref=None,
):
    return {
        "sharing_pool_id": pool_id,
        "routing_revision": routing_revision,
        "alias_affinities": [{"logical_alias": alias, "affinity": affinity} for alias, affinity in alias_affinities],
        "spend_account_refs": list(spend),
        **({"provider_pool_ref": provider_pool_ref} if provider_pool_ref else {}),
    }


def _binding_dto(
    binding_id="binding-a",
    *,
    pool_id="pool-a",
    profile_id="coding",
    facets=(SharingFacet.PROFILE, SharingFacet.SPEND),
    priority=0,
    mode="dynamic",
    selector=None,
    effective_from=_FROM,
    effective_until=_UNTIL,
    deployment_id=_DEPLOYMENT,
    membership_revision=1,
):
    payload = {
        "contract_version": "model-access-sharing/v1",
        "sharing_binding_id": binding_id,
        "deployment_id": str(deployment_id),
        "selector": selector or {"kind": "all_ranges"},
        "membership_mode": mode,
        "membership_revision": membership_revision,
        "authorized_publisher_ref": {"owner": "attacker", "reference": "forged:publisher"},
        "profile_id": profile_id,
        "sharing_pool_id": pool_id,
        "facets": [facet.value for facet in facets],
        "priority": priority,
        "effective_from": effective_from,
        "effective_until": effective_until,
    }
    return seal_sharing_binding(payload)


def _services():
    from engine.services import (
        SharingError,
        drain_sharing_binding,
        get_or_create_allocation_group,
        invalidate_sharing_authority,
        preview_effective_policy,
        project_selector_resolution,
        publish_authority_fence,
        publish_membership_projection,
        publish_sharing_binding,
        validate_sharing_binding,
    )

    return {
        "SharingError": SharingError,
        "drain": drain_sharing_binding,
        "alloc_group": get_or_create_allocation_group,
        "preview": preview_effective_policy,
        "project_resolution": project_selector_resolution,
        "fence": publish_authority_fence,
        "membership": publish_membership_projection,
        "invalidate": invalidate_sharing_authority,
        "publish": publish_sharing_binding,
        "validate": validate_sharing_binding,
    }


def _membership(
    svc,
    binding_id,
    *,
    deployment=_DEPLOYMENT,
    selector_digest=_ALL_RANGES_DIGEST,
    members=("range:r-1",),
    fresh=True,
    revision=1,
    publisher_scope=PublisherAuthorityScope.DEPLOYMENT,
    spending_eligibilities=(),
    observed_at=None,
    authority_revision=None,
    publish_fences=True,
):
    now = observed_at or timezone.now()
    authority_revision = authority_revision or revision
    deadline = now + (timedelta(hours=1) if fresh else timedelta(seconds=-30))
    member_refs = tuple({"owner": "deployment", "reference": member} for member in members)
    selector_authority_ref = {"owner": "engine", "reference": f"selector:{binding_id}"}
    publisher_authority_ref = {"owner": "management", "reference": "operator:platform"}
    if publish_fences:
        svc["fence"](
            deployment_id=deployment,
            authority_ref=selector_authority_ref,
            authority_revision=authority_revision,
            state="allowed",
        )
        svc["fence"](
            deployment_id=deployment,
            authority_ref=publisher_authority_ref,
            authority_revision=authority_revision,
            state="allowed",
        )
    subject_authorizations = []
    for member_ref in member_refs:
        authority_ref = {"owner": "cms", "reference": member_ref["reference"]}
        if publish_fences:
            svc["fence"](
                deployment_id=deployment,
                authority_ref=authority_ref,
                authority_revision=authority_revision,
                state="allowed",
            )
        subject_authorizations.append(
            {
                "subject_ref": member_ref,
                "authority_ref": authority_ref,
                "authority_revision": authority_revision,
                "state": "allowed",
            }
        )
    if publish_fences:
        for eligibility in spending_eligibilities:
            svc["fence"](
                deployment_id=deployment,
                authority_ref=eligibility["authority_ref"],
                authority_revision=eligibility["eligibility_revision"],
                state=eligibility["state"],
            )
    return svc["membership"](
        evidence=SharingAuthorityEvidence(
            contract_version="model-access-sharing-authority/v1",
            deployment_id=deployment,
            sharing_binding_id=binding_id,
            selector_digest=selector_digest,
            membership_revision=revision,
            assessment_count=len(member_refs),
            selector_authorities=(
                {
                    "authority_ref": selector_authority_ref,
                    "authority_revision": authority_revision,
                    "state": "allowed",
                },
            ),
            state="allowed",
            member_refs=member_refs,
            subject_authorizations=tuple(subject_authorizations),
            publisher_authorities=(
                {
                    "publisher_ref": _PUBLISHER,
                    "authority_ref": publisher_authority_ref,
                    "authority_revision": authority_revision,
                    "selector_digest": selector_digest,
                    "scope": publisher_scope,
                    "state": "allowed",
                },
            ),
            spending_eligibilities=spending_eligibilities,
            observed_at=now - timedelta(minutes=1),
            freshness_deadline=deadline,
        ),
    )


def _publish(
    svc,
    catalog,
    binding,
    pool,
    *,
    deployment=_DEPLOYMENT,
    expected=0,
    ack=False,
    membership=True,
    members=("range:r-1",),
):
    if membership:
        from engine.models import MembershipProjection

        selector_digest = compute_digest(binding.selector)
        if not MembershipProjection.objects.filter(
            deployment_id=deployment,
            sharing_binding_id=binding.sharing_binding_id,
            selector_digest=selector_digest,
        ).exists():
            _membership(
                svc,
                binding.sharing_binding_id,
                deployment=deployment,
                selector_digest=selector_digest,
                members=members,
            )
    return svc["publish"](
        deployment_id=deployment,
        catalog=catalog,
        binding=binding,
        pool=pool,
        publisher_identity=_PUBLISHER,
        expected_definition_revision=expected,
        empty_snapshot_ack=ack,
    )


def _preview(svc, catalog, *, deployment=_DEPLOYMENT, subject=_SUBJECT, evaluated_at=None):
    return svc["preview"](deployment_id=deployment, catalog=catalog, subject=subject, evaluated_at=evaluated_at)


def test_publish_persists_immutable_revision_with_pinned_catalog_and_publisher():
    from engine.models import SharingBindingRecord, SharingBindingRevision, SharingPoolRecord

    svc = _services()
    catalog = _catalog()
    revision = _publish(svc, catalog, _binding_dto(), _pool_dto())

    assert revision.definition_revision == 1
    assert revision.state == "active"
    # The forged publisher in the payload is ignored; the server-derived identity wins.
    assert revision.publisher_owner == "deployment"
    assert revision.publisher_reference == "operator:platform"
    assert revision.definition_digest.startswith("sha256:")
    assert revision.observed_assessment_count == 1
    # The catalog digest and profile are pinned at publication.
    assert revision.catalog_digest == catalog.digest
    assert revision.resolved_profile["profile_id"] == "coding"
    assert SharingBindingRecord.objects.filter(deployment_id=_DEPLOYMENT, sharing_binding_id="binding-a").count() == 1
    assert SharingBindingRevision.objects.filter(binding__sharing_binding_id="binding-a").count() == 1
    assert SharingPoolRecord.objects.filter(deployment_id=_DEPLOYMENT, sharing_pool_id="pool-a").count() == 1


def test_publish_enforces_optimistic_revision_fence():
    svc = _services()
    catalog = _catalog()
    _publish(svc, catalog, _binding_dto(), _pool_dto(), expected=0)

    bumped = _binding_dto(priority=5)
    pool = _pool_dto()
    with pytest.raises(svc["SharingError"]) as exc:
        _publish(svc, catalog, bumped, pool, expected=0)
    assert exc.value.code == "sharing.revision_conflict"

    second = _publish(svc, catalog, bumped, pool, expected=1)
    assert second.definition_revision == 2


def test_publish_requires_fresh_revision_matched_membership_evidence():
    svc = _services()
    catalog = _catalog()

    # Missing evidence denies (finding 2: a restriction must never publish without
    # membership the resolver can later prove applies).
    binding = _binding_dto()
    pool = _pool_dto()
    with pytest.raises(svc["SharingError"]) as missing:
        _publish(svc, catalog, binding, pool, membership=False)
    assert missing.value.code == "sharing.membership_evidence_required"

    # Stale evidence denies.
    _membership(svc, "binding-a", fresh=False, revision=2)
    with pytest.raises(svc["SharingError"]) as stale:
        _publish(svc, catalog, binding, pool, membership=False)
    assert stale.value.code == "sharing.membership_evidence_required"


def test_publish_rejects_unknown_catalog_reference():
    svc = _services()
    catalog = _catalog()
    ghost = _binding_dto(profile_id="ghost")
    pool = _pool_dto()
    with pytest.raises(svc["SharingError"]) as exc:
        _publish(svc, catalog, ghost, pool)
    assert exc.value.code.startswith("sharing.")


def test_publish_rejects_foreign_deployment_binding():
    svc = _services()
    catalog = _catalog()
    foreign = _binding_dto(deployment_id=_OTHER_DEPLOYMENT)
    pool = _pool_dto()
    with pytest.raises(svc["SharingError"]) as exc:
        _publish(svc, catalog, foreign, pool)
    assert exc.value.code == "sharing.foreign_deployment"


def test_routing_revision_bump_preserves_stable_account_ids():
    svc = _services()
    catalog = _catalog()
    _publish(svc, catalog, _binding_dto(), _pool_dto(routing_revision=1))

    # Changing routing/affinity is allowed and advances the routing revision.
    changed_routing = _pool_dto(routing_revision=2, alias_affinities=(("coding-main", "per_user"),))
    _publish(svc, catalog, _binding_dto(priority=1), changed_routing, expected=1)

    from engine.models import SharingPoolRecord

    pool = SharingPoolRecord.objects.get(deployment_id=_DEPLOYMENT, sharing_pool_id="pool-a")
    assert pool.routing_revision == 2
    assert pool.spend_account_refs == ["acct-shared"]

    # Changing a financial account identity on an existing pool is refused.
    conflicting = _binding_dto(priority=2)
    changed_accounts = _pool_dto(routing_revision=3, spend=("acct-different",))
    with pytest.raises(svc["SharingError"]) as exc:
        _publish(svc, catalog, conflicting, changed_accounts, expected=2)
    assert exc.value.code == "sharing.account_identity_changed"


def test_routing_content_change_under_same_revision_is_rejected():
    svc = _services()
    catalog = _catalog()
    _publish(
        svc, catalog, _binding_dto(), _pool_dto(routing_revision=1, alias_affinities=(("coding-main", "per_pool"),))
    )

    # Same routing revision, different affinity content: a routing revision must
    # identify a stable routing choice (finding 5).
    reused_revision = _binding_dto(priority=1)
    changed_affinity = _pool_dto(routing_revision=1, alias_affinities=(("coding-main", "per_user"),))
    with pytest.raises(svc["SharingError"]) as exc:
        _publish(svc, catalog, reused_revision, changed_affinity, expected=1)
    assert exc.value.code == "sharing.routing_content_changed"

    from engine.models import SharingPoolRecord

    pool = SharingPoolRecord.objects.get(deployment_id=_DEPLOYMENT, sharing_pool_id="pool-a")
    assert pool.alias_affinities == [{"logical_alias": "coding-main", "affinity": "per_pool"}]


def test_empty_snapshot_requires_explicit_acknowledgement():
    svc = _services()
    catalog = _catalog()
    _membership(svc, "binding-a", members=())

    snapshot = _binding_dto(mode="snapshot")
    pool = _pool_dto()
    with pytest.raises(svc["SharingError"]) as exc:
        _publish(svc, catalog, snapshot, pool, membership=False)
    assert exc.value.code == "sharing.empty_snapshot_unacknowledged"

    acked = _publish(svc, catalog, snapshot, pool, membership=False, ack=True)
    assert acked.empty_snapshot_ack is True


def test_preview_compiles_overlapping_bindings_with_deduped_accounts():
    svc = _services()
    catalog = _catalog()
    _publish(
        svc, catalog, _binding_dto("binding-a", pool_id="pool-a"), _pool_dto("pool-a", spend=("acct-shared", "acct-a"))
    )
    _publish(
        svc, catalog, _binding_dto("binding-b", pool_id="pool-b"), _pool_dto("pool-b", spend=("acct-shared", "acct-b"))
    )

    policy = _preview(svc, catalog)
    assert policy.spend_account_refs == ("acct-a", "acct-b", "acct-shared")
    assert len(policy.contributions) == 2
    assert policy.admissible is True


def test_preview_fails_closed_on_stale_membership():
    svc = _services()
    catalog = _catalog()
    _publish(svc, catalog, _binding_dto("binding-a"), _pool_dto("pool-a"))
    _membership(svc, "binding-a", fresh=False, revision=2)

    policy = _preview(svc, catalog)
    assert policy.stale is True
    assert policy.effective_profile is None


def test_preview_uses_pinned_profile_and_refuses_replaced_catalog():
    svc = _services()
    catalog_a = _catalog(spend_cap=5_000_000)
    _publish(svc, catalog_a, _binding_dto(), _pool_dto())

    # Same profile id, higher ceiling, different digest (finding 1): resolution
    # must not adopt the replacement catalog's higher limit.
    catalog_b = _catalog(spend_cap=9_000_000)
    assert catalog_b.digest != catalog_a.digest

    denied = _preview(svc, catalog_b)
    assert denied.stale is True
    assert denied.effective_profile is None

    # Against the pinned catalog the frozen profile limit applies unchanged.
    allowed = _preview(svc, catalog_a)
    assert allowed.effective_profile is not None
    assert allowed.effective_profile.limits.max_spend_micro_units == 5_000_000


def test_snapshot_membership_is_frozen_at_publication():
    svc = _services()
    catalog = _catalog()
    _membership(svc, "binding-a", members=("range:r-1",))
    _publish(svc, catalog, _binding_dto(mode="snapshot"), _pool_dto(), membership=False)

    # A later membership addition must not contribute without republishing.
    _membership(svc, "binding-a", members=("range:r-1", "range:r-2"), revision=2)

    for_r2 = _preview(svc, catalog, subject={"owner": "deployment", "reference": "range:r-2"})
    assert for_r2.contributions == ()

    for_r1 = _preview(svc, catalog, subject={"owner": "deployment", "reference": "range:r-1"})
    assert len(for_r1.contributions) == 1


def test_acknowledged_empty_snapshot_never_means_all_ranges():
    svc = _services()
    catalog = _catalog()
    _membership(svc, "binding-a", members=())
    _publish(svc, catalog, _binding_dto(mode="snapshot"), _pool_dto(), membership=False, ack=True)

    policy = _preview(svc, catalog)
    assert policy.contributions == ()


def test_expired_binding_does_not_contribute():
    svc = _services()
    catalog = _catalog()
    _publish(svc, catalog, _binding_dto(), _pool_dto())

    from datetime import datetime

    expired = _preview(svc, catalog, evaluated_at=datetime(2026, 11, 1, tzinfo=UTC))
    assert expired.contributions == ()

    active = _preview(svc, catalog, evaluated_at=datetime(2026, 9, 15, tzinfo=UTC))
    assert len(active.contributions) == 1


def test_drain_tombstones_binding_and_advances_fence_without_dropping_accounts():
    svc = _services()
    catalog = _catalog()
    projection = _membership(svc, "binding-a")
    _publish(svc, catalog, _binding_dto("binding-a"), _pool_dto("pool-a"), membership=False)
    fence_before = projection.fence_revision

    terminal = svc["drain"](
        deployment_id=_DEPLOYMENT,
        sharing_binding_id="binding-a",
        publisher_identity=_PUBLISHER,
        expected_definition_revision=1,
    )
    assert terminal.state == "tombstoned"

    from engine.models import MembershipProjection, SharingBindingRecord, SharingPoolRecord

    record = SharingBindingRecord.objects.get(deployment_id=_DEPLOYMENT, sharing_binding_id="binding-a")
    assert record.state == "tombstoned"
    projection.refresh_from_db()
    assert projection.fence_revision > fence_before
    # The pool and its account references survive the withdrawal (no refund/reset).
    pool = SharingPoolRecord.objects.get(deployment_id=_DEPLOYMENT, sharing_pool_id="pool-a")
    assert pool.spend_account_refs == ["acct-shared"]
    assert MembershipProjection.objects.filter(deployment_id=_DEPLOYMENT, sharing_binding_id="binding-a").exists()

    # A drained binding no longer contributes to the effective policy.
    assert _preview(svc, catalog).contributions == ()


def test_allocation_group_identity_is_stable_and_idempotent():
    svc = _services()
    catalog = _catalog()
    _publish(svc, catalog, _binding_dto(), _pool_dto())

    first = svc["alloc_group"](
        deployment_id=_DEPLOYMENT,
        sharing_pool_id="pool-a",
        routing_revision=1,
        affinity="per_user",
        owner_ref="user:u-1",
    )
    again = svc["alloc_group"](
        deployment_id=_DEPLOYMENT,
        sharing_pool_id="pool-a",
        routing_revision=1,
        affinity="per_user",
        owner_ref="user:u-1",
    )
    assert first == again
    assert isinstance(first, UUID)

    other_owner = svc["alloc_group"](
        deployment_id=_DEPLOYMENT,
        sharing_pool_id="pool-a",
        routing_revision=1,
        affinity="per_user",
        owner_ref="user:u-2",
    )
    assert other_owner != first

    # A new routing revision is a distinct allocation group even for the same owner.
    new_revision = svc["alloc_group"](
        deployment_id=_DEPLOYMENT,
        sharing_pool_id="pool-a",
        routing_revision=2,
        affinity="per_user",
        owner_ref="user:u-1",
    )
    assert new_revision != first

    pooled = svc["alloc_group"](
        deployment_id=_DEPLOYMENT, sharing_pool_id="pool-a", routing_revision=1, affinity="per_pool"
    )
    assert pooled != first


def test_pool_routing_revision_is_immutable_across_bindings():
    svc = _services()
    catalog = _catalog()
    per_pool = _pool_dto("pool-a", routing_revision=1, alias_affinities=(("coding-main", "per_pool"),))
    _publish(svc, catalog, _binding_dto("binding-a", pool_id="pool-a"), per_pool)
    _publish(svc, catalog, _binding_dto("binding-b", pool_id="pool-a"), per_pool)

    # Update only binding-b's routing, advancing the pool to a new revision.
    per_user_v2 = _pool_dto("pool-a", routing_revision=2, alias_affinities=(("coding-main", "per_user"),))
    _publish(svc, catalog, _binding_dto("binding-b", pool_id="pool-a", priority=1), per_user_v2, expected=1)

    from engine.models import SharingBindingRecord, SharingBindingRevision, SharingPoolRecord, SharingPoolRevision

    a = SharingBindingRecord.objects.get(deployment_id=_DEPLOYMENT, sharing_binding_id="binding-a")
    a_rev = SharingBindingRevision.objects.get(binding=a, definition_revision=a.current_definition_revision)
    # binding-a keeps its pinned routing revision even though the pool advanced.
    assert a_rev.pool_routing_revision == 1

    pool = SharingPoolRecord.objects.get(deployment_id=_DEPLOYMENT, sharing_pool_id="pool-a")
    assert pool.routing_revision == 2
    rev1 = SharingPoolRevision.objects.get(pool=pool, routing_revision=1)
    rev2 = SharingPoolRevision.objects.get(pool=pool, routing_revision=2)
    assert rev1.alias_affinities == [{"logical_alias": "coding-main", "affinity": "per_pool"}]
    assert rev2.alias_affinities == [{"logical_alias": "coding-main", "affinity": "per_user"}]


def test_membership_evidence_is_bound_to_the_published_selector():
    svc = _services()
    catalog = _catalog()
    binding_r1 = _binding_dto("binding-a", selector={"kind": "selected_ranges", "ids": ["r-1"]})
    _membership(svc, "binding-a", selector_digest=compute_digest(binding_r1.selector), members=("range:r-1",))
    _publish(svc, catalog, binding_r1, _pool_dto(), membership=False)

    # Editing the selector to a different range cannot reuse the first selector's
    # evidence (finding: evidence is bound to the exact published selector).
    binding_r2 = _binding_dto("binding-a", selector={"kind": "selected_ranges", "ids": ["r-2"]}, priority=1)
    pool = _pool_dto()
    with pytest.raises(svc["SharingError"]) as exc:
        _publish(svc, catalog, binding_r2, pool, expected=1, membership=False)
    assert exc.value.code == "sharing.membership_evidence_required"


def test_replacement_selector_evidence_does_not_clobber_active_evidence():
    svc = _services()
    catalog = _catalog()
    binding_r1 = _binding_dto("binding-a", selector={"kind": "selected_ranges", "ids": ["r-1"]})
    _membership(svc, "binding-a", selector_digest=compute_digest(binding_r1.selector), members=("range:r-1",))
    _publish(svc, catalog, binding_r1, _pool_dto(), membership=False)

    # Draft evidence for a different selector must not disturb the active one.
    binding_r2 = _binding_dto("binding-a", selector={"kind": "selected_ranges", "ids": ["r-2"]})
    _membership(svc, "binding-a", selector_digest=compute_digest(binding_r2.selector), members=("range:r-2",))

    from engine.models import MembershipProjection

    assert MembershipProjection.objects.filter(deployment_id=_DEPLOYMENT, sharing_binding_id="binding-a").count() == 2

    # The active definition (selector R1) still resolves for range:r-1.
    policy = _preview(svc, catalog, subject={"owner": "deployment", "reference": "range:r-1"})
    assert len(policy.contributions) == 1


def test_sharing_operations_are_isolated_across_deployments():
    # The deployment_id filter is the sole tenant boundary for preview, drain and
    # membership; prove it actually excludes another deployment's rows for the
    # same sharing_binding_id / pool_id.
    svc = _services()
    cat_a = _catalog(_DEPLOYMENT)
    cat_b = _catalog(_OTHER_DEPLOYMENT)
    _publish(
        svc,
        cat_a,
        _binding_dto("binding-a", deployment_id=_DEPLOYMENT),
        _pool_dto("pool-a", spend=("acct-a-deploy",)),
        deployment=_DEPLOYMENT,
    )
    _publish(
        svc,
        cat_b,
        _binding_dto("binding-a", deployment_id=_OTHER_DEPLOYMENT),
        _pool_dto("pool-a", spend=("acct-b-deploy",)),
        deployment=_OTHER_DEPLOYMENT,
    )

    # (1) preview never leaks the other deployment's accounts.
    policy_a = _preview(svc, cat_a, deployment=_DEPLOYMENT)
    policy_b = _preview(svc, cat_b, deployment=_OTHER_DEPLOYMENT)
    assert policy_a.spend_account_refs == ("acct-a-deploy",)
    assert policy_b.spend_account_refs == ("acct-b-deploy",)

    # (2) draining one deployment's binding does not tombstone the other's.
    svc["drain"](
        deployment_id=_OTHER_DEPLOYMENT,
        sharing_binding_id="binding-a",
        publisher_identity=_PUBLISHER,
        expected_definition_revision=1,
    )
    from engine.models import MembershipProjection, SharingBindingRecord

    assert SharingBindingRecord.objects.get(deployment_id=_DEPLOYMENT, sharing_binding_id="binding-a").state == "active"
    assert (
        SharingBindingRecord.objects.get(deployment_id=_OTHER_DEPLOYMENT, sharing_binding_id="binding-a").state
        == "tombstoned"
    )

    # (3) membership writes are per-deployment and independent.
    before = MembershipProjection.objects.get(deployment_id=_DEPLOYMENT, sharing_binding_id="binding-a").member_refs
    _membership(svc, "binding-a", deployment=_OTHER_DEPLOYMENT, members=("range:x",), revision=9)
    after = MembershipProjection.objects.get(deployment_id=_DEPLOYMENT, sharing_binding_id="binding-a").member_refs
    assert after == before


def test_validate_sharing_binding_accepts_resolvable_and_rejects_missing_pool_facet():
    svc = _services()
    catalog = _catalog()
    # A capacity facet with no capacity account on the pool is an incomplete definition.
    bad = _binding_dto(facets=(SharingFacet.CAPACITY,))
    pool = _pool_dto()
    with pytest.raises(svc["SharingError"]):
        svc["validate"](deployment_id=_DEPLOYMENT, catalog=catalog, binding=bad, pool=pool)

    good = _binding_dto(facets=(SharingFacet.SPEND,))
    svc["validate"](deployment_id=_DEPLOYMENT, catalog=catalog, binding=good, pool=_pool_dto())
