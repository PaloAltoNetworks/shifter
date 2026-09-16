"""Engine persistence for model-access authority fences and projections."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from shared.model_access import (
    AuthorityInvalidation,
    AuthorityState,
    OwnedReference,
    PublisherAuthorityEvidence,
    SelectorAuthorityEvidence,
    SelectorResolution,
    SharingAuthorityEvidence,
    SpendingEligibilityEvidence,
    SubjectAuthorizationEvidence,
    compute_digest,
)

from ._sharing_persistence import (
    SharingError,
    _as_evidence,
    _as_ref,
    _audit,
    _require_projection_fences,
)

if TYPE_CHECKING:
    from engine.models import MembershipProjection, SharingAuthorityFence


def publish_authority_fence(
    *,
    deployment_id: UUID,
    authority_ref: OwnedReference | dict[str, str],
    authority_revision: int,
    state: AuthorityState | str,
) -> SharingAuthorityFence:
    """Publish one monotonic shared authority revision inside the caller transaction."""
    from engine.models import SharingAuthorityFence

    reference = _as_ref(authority_ref)
    try:
        resolved_state = state if isinstance(state, AuthorityState) else AuthorityState(state)
    except ValueError as exc:
        raise SharingError("sharing.invalid_authority_state") from exc
    if isinstance(authority_revision, bool) or not isinstance(authority_revision, int) or authority_revision <= 0:
        raise SharingError("sharing.invalid_authority_revision")

    with transaction.atomic():
        fence = (
            SharingAuthorityFence.objects.select_for_update()
            .filter(
                deployment_id=deployment_id,
                authority_owner=reference.owner,
                authority_reference=reference.reference,
            )
            .first()
        )
        if fence is None:
            return SharingAuthorityFence.objects.create(
                deployment_id=deployment_id,
                authority_owner=reference.owner,
                authority_reference=reference.reference,
                authority_revision=authority_revision,
                state=resolved_state.value,
            )
        if authority_revision < fence.authority_revision:
            raise SharingError("sharing.authority_revision_regressed")
        if authority_revision == fence.authority_revision:
            if fence.state != resolved_state.value:
                raise SharingError("sharing.authority_revision_conflict")
            return fence
        fence.authority_revision = authority_revision
        fence.state = resolved_state.value
        fence.save(update_fields=["authority_revision", "state", "updated_at"])
        return fence


def invalidate_sharing_authority(command: AuthorityInvalidation | dict[str, object]) -> int:
    """Synchronously advance every matching owner fence before bounded fan-out.

    A deployment-scoped command creates a missing fence so a mutation racing
    first publication is deny-authoritative. A deployment-agnostic identity or
    workspace mutation advances every existing deployment row and creates
    nothing when no live projection has ever referenced that owner fact.
    """
    from engine.models import SharingAuthorityFence

    command = command if isinstance(command, AuthorityInvalidation) else AuthorityInvalidation.model_validate(command)
    wanted = Q()
    for reference in command.authority_refs:
        wanted |= Q(
            authority_owner=reference.owner,
            authority_reference=reference.reference,
        )

    changed = 0
    with transaction.atomic():
        rows_query = SharingAuthorityFence.objects.select_for_update().filter(wanted)
        if command.deployment_id is not None:
            rows_query = rows_query.filter(deployment_id=command.deployment_id)
        rows = list(rows_query.order_by("deployment_id", "authority_owner", "authority_reference"))
        existing = {(row.deployment_id, row.authority_owner, row.authority_reference): row for row in rows}
        for row in rows:
            row.authority_revision += 1
            row.state = command.state.value
            row.save(update_fields=["authority_revision", "state", "updated_at"])
            changed += 1

        if command.deployment_id is not None:
            for reference in command.authority_refs:
                key = (command.deployment_id, reference.owner, reference.reference)
                if key in existing:
                    continue
                SharingAuthorityFence.objects.create(
                    deployment_id=command.deployment_id,
                    authority_owner=reference.owner,
                    authority_reference=reference.reference,
                    authority_revision=1,
                    state=command.state.value,
                )
                changed += 1
    return changed


def _refresh_authority_fences(
    *, deployment_id: UUID, authority_refs: tuple[OwnedReference, ...]
) -> dict[tuple[str, str], int]:
    """Make freshly resolved owner facts allowed and return their checked revisions."""
    from engine.models import SharingAuthorityFence

    revisions: dict[tuple[str, str], int] = {}
    for reference in sorted(authority_refs, key=lambda item: (item.owner, item.reference)):
        key = (reference.owner, reference.reference)
        if key in revisions:
            continue
        fence = (
            SharingAuthorityFence.objects.select_for_update()
            .filter(
                deployment_id=deployment_id,
                authority_owner=reference.owner,
                authority_reference=reference.reference,
            )
            .first()
        )
        if fence is None:
            fence = SharingAuthorityFence.objects.create(
                deployment_id=deployment_id,
                authority_owner=reference.owner,
                authority_reference=reference.reference,
                authority_revision=1,
                state=AuthorityState.ALLOWED.value,
            )
        elif fence.state != AuthorityState.ALLOWED.value:
            fence.authority_revision += 1
            fence.state = AuthorityState.ALLOWED.value
            fence.save(update_fields=["authority_revision", "state", "updated_at"])
        revisions[key] = fence.authority_revision
    return revisions


def project_selector_resolution(
    *,
    deployment_id: UUID,
    sharing_binding_id: str,
    publisher_identity: OwnedReference | dict[str, str],
    resolution: SelectorResolution | dict[str, object],
    observed_at: datetime,
    freshness_deadline: datetime,
) -> MembershipProjection:
    """Turn a locked owner resolution into the next Engine authority projection."""
    from engine.models import MembershipProjection

    publisher = _as_ref(publisher_identity)
    resolution = (
        resolution if isinstance(resolution, SelectorResolution) else SelectorResolution.model_validate(resolution)
    )
    all_refs = (
        resolution.selector_authority_refs
        + tuple(item.authority_ref for item in resolution.subject_authorities)
        + tuple(item.authority_ref for item in resolution.publisher_requirements)
        + tuple(item.authority_ref for item in resolution.spending_eligibilities)
    )
    with transaction.atomic():
        current = (
            MembershipProjection.objects.select_for_update()
            .filter(
                deployment_id=deployment_id,
                sharing_binding_id=sharing_binding_id,
                selector_digest=resolution.selector_digest,
            )
            .first()
        )
        revisions = _refresh_authority_fences(deployment_id=deployment_id, authority_refs=all_refs)
        membership_revision = 1 if current is None else current.membership_revision + 1
        evidence = SharingAuthorityEvidence(
            contract_version="model-access-sharing-authority/v1",
            deployment_id=deployment_id,
            sharing_binding_id=sharing_binding_id,
            selector_digest=resolution.selector_digest,
            membership_revision=membership_revision,
            assessment_count=resolution.assessment_count,
            selector_authorities=tuple(
                SelectorAuthorityEvidence(
                    authority_ref=reference,
                    authority_revision=revisions[(reference.owner, reference.reference)],
                    state=AuthorityState.ALLOWED,
                )
                for reference in resolution.selector_authority_refs
            ),
            state=AuthorityState.ALLOWED,
            member_refs=resolution.member_refs,
            subject_authorizations=tuple(
                SubjectAuthorizationEvidence(
                    subject_ref=item.subject_ref,
                    authority_ref=item.authority_ref,
                    authority_revision=revisions[(item.authority_ref.owner, item.authority_ref.reference)],
                    state=AuthorityState.ALLOWED,
                )
                for item in resolution.subject_authorities
            ),
            publisher_authorities=tuple(
                PublisherAuthorityEvidence(
                    publisher_ref=publisher,
                    authority_ref=item.authority_ref,
                    authority_revision=revisions[(item.authority_ref.owner, item.authority_ref.reference)],
                    selector_digest=item.selector_digest,
                    scope=item.scope,
                    state=AuthorityState.ALLOWED,
                )
                for item in resolution.publisher_requirements
            ),
            spending_eligibilities=tuple(
                SpendingEligibilityEvidence(
                    authority_ref=item.authority_ref,
                    eligibility_revision=revisions[(item.authority_ref.owner, item.authority_ref.reference)],
                    basis=item.basis,
                    state=AuthorityState.ALLOWED,
                )
                for item in resolution.spending_eligibilities
            ),
            observed_at=observed_at,
            freshness_deadline=freshness_deadline,
        )
        return publish_membership_projection(evidence=evidence)


def publish_membership_projection(
    *,
    evidence: SharingAuthorityEvidence | dict[str, object],
) -> MembershipProjection:
    """Write one canonical, monotonic membership and authority projection.

    Keyed by ``selector_digest`` so evidence for a new selector version is a
    distinct row and never clobbers the evidence the active definition resolves
    against, even when a subsequent publication fails.
    """
    from engine.models import MembershipProjection

    evidence = _as_evidence(evidence)
    evidence_digest = compute_digest(evidence)
    payload = evidence.model_dump(mode="json")
    with transaction.atomic():
        projection = (
            MembershipProjection.objects.select_for_update()
            .filter(
                deployment_id=evidence.deployment_id,
                sharing_binding_id=evidence.sharing_binding_id,
                selector_digest=evidence.selector_digest,
            )
            .first()
        )
        _require_projection_fences(evidence)
        if projection is not None and evidence.membership_revision < projection.membership_revision:
            raise SharingError("sharing.membership_revision_regressed")
        if projection is not None and evidence.membership_revision == projection.membership_revision:
            if projection.evidence_digest != evidence_digest:
                raise SharingError("sharing.membership_revision_conflict")
            return projection

        values = {
            "membership_revision": evidence.membership_revision,
            "assessment_count": evidence.assessment_count,
            "state": evidence.state.value,
            "member_refs": payload["member_refs"],
            "selector_authorities": payload["selector_authorities"],
            "evidence_digest": evidence_digest,
            "subject_authorizations": payload["subject_authorizations"],
            "publisher_authorities": payload["publisher_authorities"],
            "spending_eligibilities": payload["spending_eligibilities"],
            "observed_at": evidence.observed_at,
            "freshness_deadline": evidence.freshness_deadline,
        }
        if projection is None:
            projection = MembershipProjection.objects.create(
                deployment_id=evidence.deployment_id,
                sharing_binding_id=evidence.sharing_binding_id,
                selector_digest=evidence.selector_digest,
                **values,
            )
        else:
            for field_name, value in values.items():
                setattr(projection, field_name, value)
            projection.save(update_fields=[*values, "updated_at"])
        _audit(
            "sharing_membership",
            entity_id=projection.pk,
            context=(
                f"binding={evidence.sharing_binding_id} membership_revision={evidence.membership_revision} "
                f"state={evidence.state.value} assessed={evidence.assessment_count} "
                f"members={len(evidence.member_refs)}"
            ),
        )
    return projection
