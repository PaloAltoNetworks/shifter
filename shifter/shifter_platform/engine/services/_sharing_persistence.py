"""Internal persistence helpers for the model-access sharing facades (PLAT-202, M19).

Split out of ``engine.services._sharing`` so the public facade module and the
persistence/resolution helpers each stay small. The facades in ``_sharing`` call
these; nothing here imports ``_sharing`` back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.utils import timezone

from shared.model_access import (
    AuthorityState,
    ModelAccessCatalog,
    PublisherAuthorityEvidence,
    PublisherAuthorityScope,
    SelectorAuthorityEvidence,
    SharingAuthorityEvidence,
    SharingBinding,
    SharingPool,
    SpendingEligibilityEvidence,
    SubjectAuthorizationEvidence,
    compute_digest,
    seal_sharing_binding,
)
from shared.model_access.core_models import OwnedReference, SelectorKind, SharingFacet

from ._common import EngineError

if TYPE_CHECKING:
    from engine.models import (
        MembershipProjection,
        SharingBindingRecord,
        SharingPoolRecord,
    )

_ACTIVE = "active"
_TOMBSTONED = "tombstoned"
_AUDIT_SOURCE = "engine.services.sharing"

# Which pool reference each shareable facet requires to be a complete definition.
_FACET_POOL_REQUIREMENT: dict[SharingFacet, str] = {
    SharingFacet.PROVIDER_IDENTITY: "provider_pool_ref",
    SharingFacet.CAPACITY: "capacity_account_ref",
    SharingFacet.ROUTING: "alias_affinities",
    SharingFacet.SPEND: "spend_account_refs",
    SharingFacet.RATE: "rate_account_refs",
    SharingFacet.CONCURRENCY: "concurrency_account_refs",
}


class SharingError(EngineError):
    """Bounded model-access sharing failure; carries a stable code, never a value."""

    def __init__(self, code: str, message: str | None = None) -> None:
        """Operation for init."""
        self.code = code
        super().__init__(message or code)


MembershipEvidence = SharingAuthorityEvidence
"""Compatibility export for the M19 name; the value is now the closed shared DTO."""


def _as_binding(binding: SharingBinding | dict[str, object]) -> SharingBinding:
    """Coerce a payload or DTO into a validated ``SharingBinding``."""
    return binding if isinstance(binding, SharingBinding) else SharingBinding.model_validate(binding)


def _as_pool(pool: SharingPool | dict[str, object]) -> SharingPool:
    """Coerce a payload or DTO into a validated ``SharingPool``."""
    return pool if isinstance(pool, SharingPool) else SharingPool.model_validate(pool)


def _as_ref(reference: OwnedReference | dict[str, str]) -> OwnedReference:
    """Coerce a payload or DTO into a validated ``OwnedReference``."""
    return reference if isinstance(reference, OwnedReference) else OwnedReference.model_validate(reference)


def _as_evidence(evidence: SharingAuthorityEvidence | dict[str, object]) -> SharingAuthorityEvidence:
    """Coerce a payload into the one closed shared authority projection contract."""
    if isinstance(evidence, SharingAuthorityEvidence):
        return evidence
    return SharingAuthorityEvidence.model_validate(evidence)


def _ref_payload(reference: OwnedReference) -> dict[str, str]:
    """Serialize a qualified reference for JSON-field membership checks."""
    return reference.model_dump(mode="json")


def _fence_matches(
    *,
    deployment_id: UUID,
    authority_ref: OwnedReference,
    revision: int,
    state: AuthorityState = AuthorityState.ALLOWED,
    lock: bool = False,
) -> bool:
    """Check one complete owner-qualified shared authority fence."""
    from engine.models import SharingAuthorityFence

    fences = SharingAuthorityFence.objects.all()
    if lock:
        fences = fences.select_for_update()
    fence = fences.filter(
        deployment_id=deployment_id,
        authority_owner=authority_ref.owner,
        authority_reference=authority_ref.reference,
    ).first()
    return bool(fence is not None and fence.authority_revision == revision and fence.state == state.value)


def _lock_fence(*, deployment_id: UUID, authority_ref: OwnedReference) -> None:
    """Acquire one authority row lock without assigning it category semantics."""
    from engine.models import SharingAuthorityFence

    SharingAuthorityFence.objects.select_for_update().filter(
        deployment_id=deployment_id,
        authority_owner=authority_ref.owner,
        authority_reference=authority_ref.reference,
    ).first()


def _require_projection_fences(evidence: SharingAuthorityEvidence) -> None:
    """Reject a projection unless every independently owned fact is current."""
    checks: list[tuple[OwnedReference, int, AuthorityState]] = [
        (item.authority_ref, item.authority_revision, item.state) for item in evidence.selector_authorities
    ]
    checks.extend((item.authority_ref, item.authority_revision, item.state) for item in evidence.subject_authorizations)
    checks.extend((item.authority_ref, item.authority_revision, item.state) for item in evidence.publisher_authorities)
    checks.extend(
        (item.authority_ref, item.eligibility_revision, item.state) for item in evidence.spending_eligibilities
    )
    for authority_ref, revision, state in sorted(
        checks,
        key=lambda item: (item[0].owner, item[0].reference, item[1], item[2].value),
    ):
        if not _fence_matches(
            deployment_id=evidence.deployment_id,
            authority_ref=authority_ref,
            revision=revision,
            state=state,
            lock=True,
        ):
            raise SharingError("sharing.authority_evidence_stale")


def _lock_persisted_projection_fences(projection: MembershipProjection) -> None:
    """Lock every persisted authority key before category-specific rechecks."""
    references = {
        (item.authority_ref.owner, item.authority_ref.reference): item.authority_ref
        for values, model in (
            (projection.selector_authorities, SelectorAuthorityEvidence),
            (projection.subject_authorizations, SubjectAuthorizationEvidence),
            (projection.publisher_authorities, PublisherAuthorityEvidence),
            (projection.spending_eligibilities, SpendingEligibilityEvidence),
        )
        for item in (model.model_validate(value) for value in values)
    }
    for reference in (references[key] for key in sorted(references)):
        _lock_fence(
            deployment_id=projection.deployment_id,
            authority_ref=reference,
        )


def _seal_with_publisher(binding: SharingBinding, publisher: OwnedReference) -> SharingBinding:
    """Re-seal a binding with the server-derived publisher so its digest is authoritative."""
    payload = binding.model_dump(mode="json")
    payload["authorized_publisher_ref"] = publisher.model_dump(mode="json")
    return seal_sharing_binding(payload)


def _require_facet_reference(facet: SharingFacet, binding: SharingBinding, pool: SharingPool) -> None:
    """Every selected facet must carry a concrete profile or pool reference."""
    if facet is SharingFacet.PROFILE:
        if binding.profile_id is None:
            raise SharingError("sharing.facet_without_reference")
        return
    attribute = _FACET_POOL_REQUIREMENT[facet]
    if not getattr(pool, attribute):
        raise SharingError("sharing.facet_without_reference")


def _resolve_catalog_profile(catalog: ModelAccessCatalog, profile_id: str | None) -> dict[str, object] | None:
    """Return the catalog profile as a JSON snapshot to freeze at publication."""
    if profile_id is None:
        return None
    for profile in catalog.profiles:
        if profile.profile_id == profile_id:
            return profile.model_dump(mode="json")
    raise SharingError("sharing.unknown_profile")


def _upsert_pool(deployment_id: UUID, pool: SharingPool) -> SharingPoolRecord:
    """Create or update the pool, keeping account identity stable and routing immutable.

    Financial-account identity is the pool's stable identity and survives routing
    revisions. Routing content (provider pool + per-alias affinity) is versioned in
    immutable ``SharingPoolRevision`` rows: an existing revision must carry
    identical content, and a new revision is appended, so a binding pinned to an
    earlier revision keeps its routing choice.
    """
    from engine.models import SharingPoolRecord, SharingPoolRevision

    payload = pool.model_dump(mode="json")
    provider = payload["provider_pool_ref"] or ""
    capacity = payload["capacity_account_ref"] or ""
    routing_revision = payload["routing_revision"]

    record = (
        SharingPoolRecord.objects.select_for_update()
        .filter(deployment_id=deployment_id, sharing_pool_id=pool.sharing_pool_id)
        .first()
    )
    if record is None:
        record = SharingPoolRecord.objects.create(
            deployment_id=deployment_id,
            sharing_pool_id=pool.sharing_pool_id,
            routing_revision=routing_revision,
            provider_pool_ref=provider,
            capacity_account_ref=capacity,
            spend_account_refs=payload["spend_account_refs"],
            rate_account_refs=payload["rate_account_refs"],
            concurrency_account_refs=payload["concurrency_account_refs"],
            alias_affinities=payload["alias_affinities"],
        )
        SharingPoolRevision.objects.create(
            pool=record,
            routing_revision=routing_revision,
            provider_pool_ref=provider,
            alias_affinities=payload["alias_affinities"],
        )
        return record

    # Financial-account identity can never be rewritten on an existing pool.
    stable_new = (
        capacity,
        payload["spend_account_refs"],
        payload["rate_account_refs"],
        payload["concurrency_account_refs"],
    )
    stable_existing = (
        record.capacity_account_ref,
        record.spend_account_refs,
        record.rate_account_refs,
        record.concurrency_account_refs,
    )
    if stable_new != stable_existing:
        raise SharingError("sharing.account_identity_changed")
    if routing_revision < record.routing_revision:
        raise SharingError("sharing.routing_revision_regressed")

    # A routing revision must identify a stable routing choice: an existing
    # revision must be byte-identical; a new revision is appended immutably.
    existing_revision = SharingPoolRevision.objects.filter(pool=record, routing_revision=routing_revision).first()
    routing_content = (provider, payload["alias_affinities"])
    if existing_revision is not None:
        if (existing_revision.provider_pool_ref, existing_revision.alias_affinities) != routing_content:
            raise SharingError("sharing.routing_content_changed")
    else:
        SharingPoolRevision.objects.create(
            pool=record,
            routing_revision=routing_revision,
            provider_pool_ref=provider,
            alias_affinities=payload["alias_affinities"],
        )

    if routing_revision > record.routing_revision:
        record.routing_revision = routing_revision
        record.provider_pool_ref = provider
        record.alias_affinities = payload["alias_affinities"]
        record.save(update_fields=["routing_revision", "provider_pool_ref", "alias_affinities", "updated_at"])
    return record


def _require_membership_evidence(
    deployment_id: UUID, sharing_binding_id: str, selector_digest: str, membership_revision: int
) -> MembershipProjection:
    """Return the fresh, revision-matched projection for this selector, or deny."""
    from engine.models import MembershipProjection

    moment = timezone.now()
    projection = (
        MembershipProjection.objects.select_for_update()
        .filter(deployment_id=deployment_id, sharing_binding_id=sharing_binding_id, selector_digest=selector_digest)
        .first()
    )
    if projection is None or not projection.is_fresh(moment) or projection.membership_revision != membership_revision:
        raise SharingError("sharing.membership_evidence_required")
    _lock_persisted_projection_fences(projection)
    for payload in projection.selector_authorities:
        authority = SelectorAuthorityEvidence.model_validate(payload)
        if authority.state is not AuthorityState.ALLOWED or not _fence_matches(
            deployment_id=deployment_id,
            authority_ref=authority.authority_ref,
            revision=authority.authority_revision,
        ):
            raise SharingError("sharing.membership_evidence_required")
    return projection


def _frozen_snapshot(
    projection: MembershipProjection, is_snapshot: bool, empty_snapshot_ack: bool
) -> list[dict[str, object]]:
    """Freeze snapshot membership at publication; an empty snapshot needs an explicit ack."""
    frozen = list(projection.member_refs) if is_snapshot else []
    if is_snapshot and not frozen and not empty_snapshot_ack:
        raise SharingError("sharing.empty_snapshot_unacknowledged")
    return frozen


def _publisher_evidence(projection: MembershipProjection) -> tuple[PublisherAuthorityEvidence, ...]:
    """Parse persisted publisher authority evidence into the closed contract."""
    return tuple(PublisherAuthorityEvidence.model_validate(item) for item in projection.publisher_authorities)


def _spending_evidence(projection: MembershipProjection) -> tuple[SpendingEligibilityEvidence, ...]:
    """Parse persisted spending eligibility evidence into the closed contract."""
    return tuple(SpendingEligibilityEvidence.model_validate(item) for item in projection.spending_eligibilities)


def _required_publisher_digests(binding: SharingBinding) -> tuple[str, ...]:
    """Return every atomic selector digest a publisher must authorize."""
    selector = binding.selector
    if selector.kind is SelectorKind.NAMED_COLLECTION:
        return tuple(sorted(compute_digest(member) for member in selector.members))
    return (compute_digest(selector),)


def _publisher_candidate_matches(
    candidate: PublisherAuthorityEvidence,
    publisher: OwnedReference,
    required_digests: tuple[str, ...],
) -> bool:
    """Return whether evidence can authorize this publisher and selector set."""
    selector_matches = (
        candidate.scope is PublisherAuthorityScope.DEPLOYMENT or candidate.selector_digest in required_digests
    )
    return candidate.publisher_ref == publisher and candidate.state is AuthorityState.ALLOWED and selector_matches


def _digest_is_authorized(digest: str, matched: tuple[PublisherAuthorityEvidence, ...]) -> bool:
    """Return whether matched evidence covers one atomic selector digest."""
    return any(item.scope is PublisherAuthorityScope.DEPLOYMENT or item.selector_digest == digest for item in matched)


def _require_publisher_authority(
    *,
    deployment_id: UUID,
    projection: MembershipProjection,
    binding: SharingBinding,
    publisher: OwnedReference,
    lock: bool = True,
) -> tuple[PublisherAuthorityEvidence, ...]:
    """Require current authority over every atomic selector in the collection."""
    evidence = _publisher_evidence(projection)
    required_digests = _required_publisher_digests(binding)
    matched = tuple(
        candidate for candidate in evidence if _publisher_candidate_matches(candidate, publisher, required_digests)
    )
    if any(not _digest_is_authorized(digest, matched) for digest in required_digests):
        raise SharingError("sharing.publisher_authority_required")
    for item in sorted(matched, key=lambda value: (value.authority_ref.owner, value.authority_ref.reference)):
        if not _fence_matches(
            deployment_id=deployment_id,
            authority_ref=item.authority_ref,
            revision=item.authority_revision,
            lock=lock,
        ):
            raise SharingError("sharing.publisher_authority_required")

    if binding.selector.kind is SelectorKind.ALL_RANGES and not any(
        item.scope is PublisherAuthorityScope.DEPLOYMENT for item in matched
    ):
        raise SharingError("sharing.deployment_operator_required")
    return matched


_FUNDED_FACETS = frozenset(
    {
        SharingFacet.PROVIDER_IDENTITY,
        SharingFacet.CAPACITY,
        SharingFacet.SPEND,
        SharingFacet.RATE,
        SharingFacet.CONCURRENCY,
    }
)


def _required_group_eligibility_refs(binding: SharingBinding) -> tuple[OwnedReference, ...]:
    """Return every group authority that must independently fund shared facets."""
    selector = binding.selector
    group_selectors = (
        (selector,)
        if selector.kind is SelectorKind.AUTH_GROUP
        else tuple(member for member in selector.members if member.kind is SelectorKind.AUTH_GROUP)
    )
    return tuple(
        OwnedReference(owner="management", reference=f"auth-group:{group_id}")
        for group_selector in group_selectors
        for group_id in group_selector.ids
    )


def _require_spending_eligibility(
    *, deployment_id: UUID, projection: MembershipProjection, binding: SharingBinding, lock: bool = True
) -> None:
    """Self-service group membership alone never activates funded facets."""
    required_refs = _required_group_eligibility_refs(binding)
    if not required_refs or not _FUNDED_FACETS.intersection(binding.facets):
        return
    evidence = _spending_evidence(projection)
    for required_ref in required_refs:
        item = next(
            (
                candidate
                for candidate in evidence
                if candidate.authority_ref == required_ref and candidate.state is AuthorityState.ALLOWED
            ),
            None,
        )
        if item is None or not _fence_matches(
            deployment_id=deployment_id,
            authority_ref=item.authority_ref,
            revision=item.eligibility_revision,
            lock=lock,
        ):
            raise SharingError("sharing.spending_eligibility_required")


def _write_binding_record(
    record: SharingBindingRecord | None,
    deployment_id: UUID,
    sealed: SharingBinding,
    pool_record: SharingPoolRecord,
    next_revision: int,
) -> SharingBindingRecord:
    """Create or advance the stable binding record to the next definition revision."""
    from engine.models import SharingBindingRecord

    if record is None:
        return SharingBindingRecord.objects.create(
            deployment_id=deployment_id,
            sharing_binding_id=sealed.sharing_binding_id,
            pool=pool_record,
            current_definition_revision=next_revision,
            state=_ACTIVE,
        )
    record.pool = pool_record
    record.current_definition_revision = next_revision
    record.state = _ACTIVE
    record.save(update_fields=["pool", "current_definition_revision", "state", "updated_at"])
    return record


def _audit(action: str, *, entity_id: int, context: str) -> None:
    """Record a bounded, fail-closed audit event inside the mutation transaction."""
    from shared.audit import AuditActorType, AuditEvent, audit_log

    audit_log(
        AuditEvent(
            entity_type="sharing_binding",
            entity_id=entity_id,
            action=action,
            actor_type=AuditActorType.SYSTEM,
            context=f"[{_AUDIT_SOURCE}] {context}",
        ),
        strict=True,
    )
