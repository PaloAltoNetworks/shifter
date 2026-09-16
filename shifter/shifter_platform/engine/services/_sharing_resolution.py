"""Effective-policy applicability helpers for persisted sharing revisions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from shared.model_access import (
    AuthorityState,
    BindingMatch,
    ModelProfile,
    OwnedReference,
    SelectorAuthorityEvidence,
    SharingBinding,
    SharingPool,
    SubjectAuthorizationEvidence,
)
from shared.model_access.core_models import MembershipMode, SharingFacet

from ._sharing_persistence import _fence_matches, _ref_payload

if TYPE_CHECKING:
    from engine.models import (
        MembershipProjection,
        SharingBindingRecord,
        SharingBindingRevision,
        SharingPoolRecord,
    )


def _pinned_pool(record: SharingPoolRecord, routing_revision: int) -> SharingPool:
    """Reconstruct a SharingPool DTO for the pinned routing revision and stable accounts."""
    from engine.models import SharingPoolRevision

    pool_revision = SharingPoolRevision.objects.filter(pool=record, routing_revision=routing_revision).first()
    provider = pool_revision.provider_pool_ref if pool_revision is not None else record.provider_pool_ref
    alias_affinities = pool_revision.alias_affinities if pool_revision is not None else record.alias_affinities
    return SharingPool.model_validate(
        {
            "sharing_pool_id": record.sharing_pool_id,
            "routing_revision": routing_revision,
            "alias_affinities": alias_affinities,
            "provider_pool_ref": provider or None,
            "capacity_account_ref": record.capacity_account_ref or None,
            "spend_account_refs": record.spend_account_refs,
            "rate_account_refs": record.rate_account_refs,
            "concurrency_account_refs": record.concurrency_account_refs,
        }
    )


def _match_for_subject(
    record: SharingBindingRecord,
    revision: SharingBindingRevision,
    subject_ref: OwnedReference,
    moment: datetime,
    catalog_digest: str,
) -> BindingMatch | None:
    """Build the BindingMatch for one active binding, or None when it does not apply.

    Uses the profile and snapshot membership frozen at publication so resolution
    never re-reads a mutated catalog or shifted live projection.
    """
    binding = SharingBinding.model_validate(revision.definition)
    catalog_ok = revision.catalog_digest == catalog_digest
    if binding.membership_mode is MembershipMode.SNAPSHOT:
        resolved = _snapshot_applicability(revision, subject_ref, moment, catalog_ok)
    else:
        resolved = _dynamic_applicability(record, revision, subject_ref, moment, catalog_ok)
    if resolved is None:
        return None
    membership_revision, membership_fresh = resolved
    return BindingMatch(
        binding=binding,
        pool=_pinned_pool(record.pool, revision.pool_routing_revision),
        profile=_pinned_profile(revision, binding),
        membership_revision=membership_revision,
        membership_fresh=membership_fresh,
        matched_reason=binding.selector.kind.value,
    )


def _snapshot_applicability(
    revision: SharingBindingRevision,
    subject_ref: OwnedReference,
    moment: datetime,
    catalog_ok: bool,
) -> tuple[int, bool] | None:
    """Keep snapshot inclusion frozen while checking live subject and selector authority."""
    resolved: tuple[int, bool] | None = None
    if _ref_payload(subject_ref) in revision.frozen_members:
        from engine.models import MembershipProjection

        current = MembershipProjection.objects.filter(
            deployment_id=revision.binding.deployment_id,
            sharing_binding_id=revision.binding.sharing_binding_id,
            selector_digest=revision.selector_digest,
        ).first()
        if current is not None:
            authorization = _subject_authorization(current, subject_ref)
            if authorization is not None and authorization.state is AuthorityState.ALLOWED:
                fence_state = _subject_fence_state(
                    deployment_id=revision.binding.deployment_id,
                    authorization=authorization,
                )
                if fence_state != "revoked":
                    resolved = (
                        current.membership_revision,
                        current.is_fresh(moment)
                        and _selector_fence_is_current(current)
                        and fence_state == "current"
                        and catalog_ok,
                    )
    return resolved


def _dynamic_applicability(
    record: SharingBindingRecord,
    revision: SharingBindingRevision,
    subject_ref: OwnedReference,
    moment: datetime,
    catalog_ok: bool,
) -> tuple[int, bool] | None:
    """Resolve dynamic applicability and freshness against the selector projection."""
    from engine.models import MembershipProjection

    resolved: tuple[int, bool] | None = None
    projection = MembershipProjection.objects.filter(
        deployment_id=record.deployment_id,
        sharing_binding_id=record.sharing_binding_id,
        selector_digest=revision.selector_digest,
    ).first()
    if projection is not None and _ref_payload(subject_ref) in projection.member_refs:
        authorization = _subject_authorization(projection, subject_ref)
        if authorization is not None and authorization.state is AuthorityState.ALLOWED:
            fence_state = _subject_fence_state(deployment_id=record.deployment_id, authorization=authorization)
            if fence_state != "revoked":
                resolved = (
                    projection.membership_revision,
                    projection.is_fresh(moment)
                    and _selector_fence_is_current(projection)
                    and fence_state == "current"
                    and catalog_ok,
                )
    return resolved


def _subject_authorization(
    projection: MembershipProjection, subject_ref: OwnedReference
) -> SubjectAuthorizationEvidence | None:
    """Load exact subject authorization from a canonical persisted projection."""
    for payload in projection.subject_authorizations:
        evidence = SubjectAuthorizationEvidence.model_validate(payload)
        if evidence.subject_ref == subject_ref:
            return evidence
    return None


def _subject_fence_state(*, deployment_id: UUID, authorization: SubjectAuthorizationEvidence) -> str:
    """Return current, stale, or revoked for one subject evidence fence."""
    from engine.models import SharingAuthorityFence

    current = SharingAuthorityFence.objects.filter(
        deployment_id=deployment_id,
        authority_owner=authorization.authority_ref.owner,
        authority_reference=authorization.authority_ref.reference,
    ).first()
    state = "stale"
    if current is not None:
        if current.state == AuthorityState.REVOKED.value:
            state = "revoked"
        elif (
            current.state == AuthorityState.ALLOWED.value
            and current.authority_revision == authorization.authority_revision
        ):
            state = "current"
    return state


def _selector_fence_is_current(projection: MembershipProjection) -> bool:
    """Return whether every selector fence is present, allowed, and current."""
    for payload in projection.selector_authorities:
        authority = SelectorAuthorityEvidence.model_validate(payload)
        if authority.state is not AuthorityState.ALLOWED or not _fence_matches(
            deployment_id=projection.deployment_id,
            authority_ref=authority.authority_ref,
            revision=authority.authority_revision,
        ):
            return False
    return bool(projection.selector_authorities)


def _pinned_profile(revision: SharingBindingRevision, binding: SharingBinding) -> ModelProfile | None:
    """Return the profile frozen at publication when the binding shares a profile."""
    if revision.resolved_profile and SharingFacet.PROFILE in binding.facets:
        return ModelProfile.model_validate(revision.resolved_profile)
    return None
