"""Engine-owned model-access sharing facades (PLAT-202, M19, #2139).

These are the authorized, revision-fenced boundary through which both
catalog-sourced and management-API drafts become live policy. Engine PostgreSQL
is the sole authority: a definition only affects a range after it passes
``publish_sharing_binding`` here.

Key invariants:

* Publisher identity is server-derived; a submitted ``authorized_publisher_ref``
  is overwritten before the definition is sealed and persisted.
* Publish is an optimistic compare-and-set on the definition revision inside a
  locked transaction, and requires fresh, selector-bound membership evidence.
* A pool's stable financial-account identity survives routing revisions; routing
  content is versioned in immutable pool routing revisions.
* Withdrawal tombstones the binding, advances the membership fence synchronously,
  and preserves the pool and its account references (no refund/reset/cascade).
* Effective-policy resolution is delegated to the single pure compiler in
  ``shared.model_access.effective_policy``; unknown or stale membership denies.

Internal persistence/resolution helpers live in ``_sharing_persistence``.
Membership *resolution* (the CTF/CMS/identity adapters) belongs to #2140; this
module owns the projection record it writes through and the freshness/fence gate.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from shared.model_access import (
    BindingMatch,
    EffectivePolicy,
    ModelAccessCatalog,
    ModelAccessRangeView,
    OwnedReference,
    SharingBinding,
    SharingPool,
    compile_effective_policy,
    compute_digest,
)
from shared.model_access.core_models import MembershipMode

from ._sharing_authority import (
    invalidate_sharing_authority,
    project_selector_resolution,
    publish_authority_fence,
    publish_membership_projection,
)
from ._sharing_persistence import (
    _ACTIVE,
    _TOMBSTONED,
    MembershipEvidence,
    SharingError,
    _as_binding,
    _as_pool,
    _as_ref,
    _audit,
    _frozen_snapshot,
    _require_facet_reference,
    _require_membership_evidence,
    _require_publisher_authority,
    _require_spending_eligibility,
    _resolve_catalog_profile,
    _seal_with_publisher,
    _upsert_pool,
    _write_binding_record,
)
from ._sharing_ranges import resolve_model_access_range_page, resolve_model_access_range_views
from ._sharing_resolution import _match_for_subject

if TYPE_CHECKING:
    from engine.models import SharingBindingRevision

__all__ = [
    "MembershipEvidence",
    "ModelAccessRangeView",
    "SharingError",
    "drain_sharing_binding",
    "get_or_create_allocation_group",
    "invalidate_sharing_authority",
    "preview_effective_policy",
    "project_selector_resolution",
    "publish_authority_fence",
    "publish_membership_projection",
    "publish_sharing_binding",
    "resolve_model_access_range_page",
    "resolve_model_access_range_views",
    "validate_sharing_binding",
]


def validate_sharing_binding(
    *,
    deployment_id: UUID,
    catalog: ModelAccessCatalog,
    binding: SharingBinding | dict,
    pool: SharingPool | dict,
) -> None:
    """Fail closed unless the binding and pool resolve against the pinned catalog.

    Confers no authority; publication rechecks everything under a lock.
    """
    binding = _as_binding(binding)
    pool = _as_pool(pool)

    if binding.deployment_id != deployment_id:
        raise SharingError("sharing.foreign_deployment")
    if catalog.deployment_id != deployment_id:
        raise SharingError("sharing.catalog_deployment_mismatch")
    if binding.sharing_pool_id != pool.sharing_pool_id:
        raise SharingError("sharing.pool_mismatch")

    catalog_profiles = {profile.profile_id for profile in catalog.profiles}
    catalog_aliases = {alias.logical_alias for alias in catalog.aliases}

    if binding.profile_id is not None and binding.profile_id not in catalog_profiles:
        raise SharingError("sharing.unknown_profile")
    for affinity in pool.alias_affinities:
        if affinity.logical_alias not in catalog_aliases:
            raise SharingError("sharing.unknown_alias")

    for facet in binding.facets:
        _require_facet_reference(facet, binding, pool)


def publish_sharing_binding(
    *,
    deployment_id: UUID,
    catalog: ModelAccessCatalog,
    binding: SharingBinding | dict,
    pool: SharingPool | dict,
    publisher_identity: OwnedReference | dict,
    expected_definition_revision: int,
    empty_snapshot_ack: bool = False,
) -> SharingBindingRevision:
    """Persist the next immutable definition revision under an optimistic fence."""
    from engine.models import SharingBindingRecord, SharingBindingRevision

    binding = _as_binding(binding)
    pool = _as_pool(pool)
    publisher = _as_ref(publisher_identity)
    validate_sharing_binding(deployment_id=deployment_id, catalog=catalog, binding=binding, pool=pool)

    # Re-seal with the server-derived publisher, and pin the resolved profile,
    # catalog digest and selector digest so resolution can never re-read a mutated
    # catalog or reuse another selector's membership evidence.
    sealed = _seal_with_publisher(binding, publisher)
    resolved_profile = _resolve_catalog_profile(catalog, sealed.profile_id)
    selector_digest = compute_digest(sealed.selector)
    is_snapshot = sealed.membership_mode is MembershipMode.SNAPSHOT

    with transaction.atomic():
        pool_record = _upsert_pool(deployment_id, pool)
        record = (
            SharingBindingRecord.objects.select_for_update()
            .filter(deployment_id=deployment_id, sharing_binding_id=sealed.sharing_binding_id)
            .first()
        )
        current = record.current_definition_revision if record is not None else 0
        if expected_definition_revision != current:
            raise SharingError("sharing.revision_conflict")

        projection = _require_membership_evidence(
            deployment_id, sealed.sharing_binding_id, selector_digest, sealed.membership_revision
        )
        publisher_authorities = _require_publisher_authority(
            deployment_id=deployment_id,
            projection=projection,
            binding=sealed,
            publisher=publisher,
            lock=False,
        )
        _require_spending_eligibility(
            deployment_id=deployment_id,
            projection=projection,
            binding=sealed,
            lock=False,
        )
        frozen_members = _frozen_snapshot(projection, is_snapshot, empty_snapshot_ack)

        next_revision = current + 1
        record = _write_binding_record(record, deployment_id, sealed, pool_record, next_revision)
        revision = SharingBindingRevision.objects.create(
            binding=record,
            definition_revision=next_revision,
            definition_digest=sealed.definition_digest,
            definition=sealed.model_dump(mode="json"),
            catalog_digest=catalog.digest,
            resolved_profile=resolved_profile,
            frozen_members=frozen_members,
            pool_routing_revision=pool.routing_revision,
            selector_digest=selector_digest,
            membership_mode=sealed.membership_mode.value,
            priority=sealed.priority,
            effective_from=sealed.effective_from,
            effective_until=sealed.effective_until,
            observed_membership_revision=projection.membership_revision,
            observed_assessment_count=projection.assessment_count,
            observed_authority_revisions=projection.selector_authorities,
            publisher_authority_revisions=[item.model_dump(mode="json") for item in publisher_authorities],
            publisher_owner=publisher.owner,
            publisher_reference=publisher.reference,
            empty_snapshot_ack=empty_snapshot_ack,
            state=_ACTIVE,
        )
        _audit(
            "sharing_publish",
            entity_id=record.pk,
            context=(
                f"binding={sealed.sharing_binding_id} revision={next_revision} "
                f"pool={sealed.sharing_pool_id} priority={sealed.priority} "
                f"facets={','.join(facet.value for facet in sealed.facets)}"
            ),
        )
    return revision


def drain_sharing_binding(
    *,
    deployment_id: UUID,
    sharing_binding_id: str,
    publisher_identity: OwnedReference | dict,
    expected_definition_revision: int,
) -> SharingBindingRevision:
    """Withdraw a binding: publish a terminal revision and fence its projections.

    Preserves the pool and every account reference; drain of the underlying
    liabilities is asynchronous and does not refund or reset any account here.
    """
    from engine.models import MembershipProjection, SharingBindingRecord, SharingBindingRevision

    publisher = _as_ref(publisher_identity)
    with transaction.atomic():
        record = (
            SharingBindingRecord.objects.select_for_update()
            .filter(deployment_id=deployment_id, sharing_binding_id=sharing_binding_id)
            .first()
        )
        if record is None:
            raise SharingError("sharing.binding_not_found")
        if expected_definition_revision != record.current_definition_revision:
            raise SharingError("sharing.revision_conflict")

        prior = record.revisions.get(definition_revision=record.current_definition_revision)
        projection = (
            MembershipProjection.objects.select_for_update()
            .filter(
                deployment_id=deployment_id,
                sharing_binding_id=sharing_binding_id,
                selector_digest=prior.selector_digest,
            )
            .first()
        )
        if projection is None:
            raise SharingError("sharing.publisher_authority_required")
        binding = SharingBinding.model_validate(prior.definition)
        publisher_authorities = _require_publisher_authority(
            deployment_id=deployment_id,
            projection=projection,
            binding=binding,
            publisher=publisher,
        )
        next_revision = record.current_definition_revision + 1
        terminal = SharingBindingRevision.objects.create(
            binding=record,
            definition_revision=next_revision,
            definition_digest=prior.definition_digest,
            definition=prior.definition,
            catalog_digest=prior.catalog_digest,
            resolved_profile=prior.resolved_profile,
            frozen_members=prior.frozen_members,
            pool_routing_revision=prior.pool_routing_revision,
            selector_digest=prior.selector_digest,
            membership_mode=prior.membership_mode,
            priority=prior.priority,
            effective_from=prior.effective_from,
            effective_until=prior.effective_until,
            observed_membership_revision=prior.observed_membership_revision,
            observed_assessment_count=prior.observed_assessment_count,
            observed_authority_revisions=prior.observed_authority_revisions,
            publisher_authority_revisions=[item.model_dump(mode="json") for item in publisher_authorities],
            publisher_owner=publisher.owner,
            publisher_reference=publisher.reference,
            empty_snapshot_ack=prior.empty_snapshot_ack,
            state=_TOMBSTONED,
        )
        record.current_definition_revision = next_revision
        record.state = _TOMBSTONED
        record.save(update_fields=["current_definition_revision", "state", "updated_at"])

        # Advance the invalidation fence synchronously so requests see the
        # withdrawal immediately, before any asynchronous reassessment.
        for projection in MembershipProjection.objects.select_for_update().filter(
            deployment_id=deployment_id, sharing_binding_id=sharing_binding_id
        ):
            projection.fence_revision += 1
            projection.save(update_fields=["fence_revision", "updated_at"])
        _audit(
            "sharing_drain",
            entity_id=record.pk,
            context=f"binding={sharing_binding_id} revision={next_revision}",
        )
    return terminal


def preview_effective_policy(
    *,
    deployment_id: UUID,
    catalog: ModelAccessCatalog,
    subject: OwnedReference | dict,
    evaluated_at: datetime | None = None,
    now: datetime | None = None,
) -> EffectivePolicy:
    """Compile the effective policy for one subject; a preview is not authority."""
    from engine.models import SharingBindingRecord

    subject_ref = _as_ref(subject)
    moment = now or timezone.now()
    evaluated = evaluated_at or moment

    matches: list[BindingMatch] = []
    active = SharingBindingRecord.objects.filter(deployment_id=deployment_id, state=_ACTIVE).select_related("pool")
    for record in active:
        revision = record.revisions.filter(
            definition_revision=record.current_definition_revision, state=_ACTIVE
        ).first()
        if revision is None:
            continue
        match = _match_for_subject(record, revision, subject_ref, moment, catalog.digest)
        if match is not None:
            matches.append(match)

    return compile_effective_policy(
        deployment_id=deployment_id,
        catalog_digest=catalog.digest,
        evaluated_at=evaluated,
        subject=subject_ref,
        matches=tuple(matches),
    )


def get_or_create_allocation_group(
    *,
    deployment_id: UUID,
    sharing_pool_id: str,
    routing_revision: int,
    affinity: str,
    owner_ref: str | None = None,
) -> UUID:
    """Return the stable allocation-group UUID for a shared assignment key.

    ``per_range`` uses the existing draw UUID and has no group here; ``per_pool``
    keys on the routing revision alone, ``per_user`` on the canonical owner.
    """
    from engine.models import AllocationGroup

    if affinity not in ("per_user", "per_pool"):
        raise SharingError("sharing.unsupported_affinity")
    resolved_owner = "" if affinity == "per_pool" else (owner_ref or "")
    if affinity == "per_user" and not resolved_owner:
        raise SharingError("sharing.owner_required")

    group, _created = AllocationGroup.objects.get_or_create(
        deployment_id=deployment_id,
        sharing_pool_id=sharing_pool_id,
        routing_revision=routing_revision,
        affinity=affinity,
        owner_ref=resolved_owner,
    )
    return group.allocation_group_id
