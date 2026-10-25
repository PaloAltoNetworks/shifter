"""Composition root for cross-domain model-access selector resolution."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from shared.model_access import (
    ModelAccessCatalog,
    OwnedReference,
    PublisherAuthorityRequirement,
    ResolvedSpendingEligibility,
    ResolvedSubjectAuthority,
    SelectorKind,
    SelectorResolution,
    SharingBinding,
    SharingPool,
    SharingSelector,
    compute_digest,
    seal_sharing_binding,
)


class ModelAccessCompositionError(Exception):
    """Opaque selector-composition failure."""

    code = "model_access.composition_denied"


_CTF_KINDS = frozenset(
    {
        SelectorKind.CTF_EVENT,
        SelectorKind.CTF_TEAM,
        SelectorKind.CTF_COHORT,
    }
)
_SELECTOR_DENIED = "Model-access selector denied"
_PUBLISHER_UNAVAILABLE = "allocation.publisher_unavailable"


def refresh_model_launch_projections(deployment_id: UUID) -> None:
    """Re-resolve stale live definitions as their recorded publisher, never as a guest.

    Each owner resolver holds its incumbent mutex through the caller's launch
    transaction. Publication races are detected again by Engine admission.
    """
    from cms.services import engine_list_model_launch_refreshes, engine_project_selector_resolution
    from management.services import get_admin_user, resolve_model_access_users
    from shared.model_access import ContractError

    for binding in engine_list_model_launch_refreshes(deployment_id):
        publisher = binding.authorized_publisher_ref
        kind, _, identity = publisher.reference.partition(":")
        if publisher.owner != "management" or kind not in {"user", "operator"} or not identity.isdecimal():
            raise ContractError(_PUBLISHER_UNAVAILABLE)
        with transaction.atomic():
            actor = get_admin_user(int(identity))
            if actor is None:
                raise ContractError(_PUBLISHER_UNAVAILABLE)
            resolve_model_access_users(actor, (actor.pk,))
            if _publisher_identity(actor) != publisher:
                raise ContractError(_PUBLISHER_UNAVAILABLE)
            resolution = resolve_model_access_selector(actor, binding.selector)
            now = timezone.now()
            engine_project_selector_resolution(
                deployment_id=deployment_id,
                sharing_binding_id=binding.sharing_binding_id,
                publisher_identity=publisher,
                resolution=resolution,
                observed_at=now,
                freshness_deadline=now + timedelta(minutes=5),
            )


def _uuid_ids(values: tuple[str, ...]) -> tuple[UUID, ...]:
    """Parse canonical UUID strings or fail without enumeration detail."""
    try:
        resolved = tuple(UUID(value) for value in values)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ModelAccessCompositionError(_SELECTOR_DENIED) from exc
    if any(str(value) != supplied for value, supplied in zip(resolved, values, strict=True)):
        raise ModelAccessCompositionError(_SELECTOR_DENIED)
    return resolved


def _combine(
    selector: SharingSelector,
    resolutions: tuple[SelectorResolution, ...],
    *,
    preserve_atomic_digests: bool,
) -> SelectorResolution:
    """Combine atomic selector resolutions into one deterministic result."""
    member_by_key: dict[tuple[str, str], OwnedReference] = {}
    subject_by_key: dict[tuple[str, str], ResolvedSubjectAuthority] = {}
    selector_authority_by_key: dict[tuple[str, str], OwnedReference] = {}
    publisher_by_key: dict[tuple[str, str, str, str], PublisherAuthorityRequirement] = {}
    spending_by_key: dict[tuple[str, str, str], ResolvedSpendingEligibility] = {}
    combined_digest = compute_digest(selector)
    for resolution in resolutions:
        for member in resolution.member_refs:
            member_by_key.setdefault((member.owner, member.reference), member)
        for subject in resolution.subject_authorities:
            subject_by_key.setdefault(
                (subject.subject_ref.owner, subject.subject_ref.reference),
                subject,
            )
        for authority in resolution.selector_authority_refs:
            selector_authority_by_key[(authority.owner, authority.reference)] = authority
        for publisher in resolution.publisher_requirements:
            normalized = (
                publisher
                if preserve_atomic_digests
                else publisher.model_copy(update={"selector_digest": combined_digest})
            )
            publisher_by_key[
                (
                    normalized.selector_digest,
                    normalized.authority_ref.owner,
                    normalized.authority_ref.reference,
                    normalized.scope.value,
                )
            ] = normalized
        for eligibility in resolution.spending_eligibilities:
            spending_by_key[
                (
                    eligibility.authority_ref.owner,
                    eligibility.authority_ref.reference,
                    eligibility.basis.value,
                )
            ] = eligibility

    return SelectorResolution(
        contract_version="model-access-selector-resolution/v1",
        selector_digest=combined_digest,
        assessment_count=len(member_by_key),
        member_refs=tuple(member_by_key.values()),
        selector_authority_refs=tuple(selector_authority_by_key.values()),
        subject_authorities=tuple(subject_by_key.values()),
        publisher_requirements=tuple(publisher_by_key.values()),
        spending_eligibilities=tuple(spending_by_key.values()),
    )


def _resolve_selected(actor: object, selector: SharingSelector) -> SelectorResolution:
    """Partition selected ranges between ordinary and CTF owner services."""
    from cms.services import resolve_model_access_range_views
    from cms.services import resolve_model_access_selector as resolve_cms_selector
    from ctf.services import classify_model_access_selected_ranges
    from ctf.services import resolve_model_access_selector as resolve_ctf_selector

    range_uuids = _uuid_ids(selector.ids)
    ranges = resolve_model_access_range_views(range_uuids=range_uuids)
    ctf_range_uuids = frozenset(classify_model_access_selected_ranges(range_uuids))
    ordinary_range_uuids = tuple(item.range_uuid for item in ranges if item.range_uuid not in ctf_range_uuids)
    resolutions: list[SelectorResolution] = []

    if ordinary_range_uuids:
        resolutions.append(
            resolve_cms_selector(
                actor,
                SharingSelector(
                    kind=SelectorKind.SELECTED_RANGES,
                    ids=tuple(str(item) for item in ordinary_range_uuids),
                ),
            )
        )
    if ctf_range_uuids:
        resolutions.append(
            resolve_ctf_selector(
                actor,
                SharingSelector(
                    kind=SelectorKind.SELECTED_RANGES,
                    ids=tuple(str(item) for item in ctf_range_uuids),
                ),
            )
        )
    if not resolutions:
        raise ModelAccessCompositionError(_SELECTOR_DENIED)
    if len(resolutions) == 1 and resolutions[0].selector_digest == compute_digest(selector):
        return resolutions[0]
    return _combine(selector, tuple(resolutions), preserve_atomic_digests=False)


def _resolve_atom(actor: object, selector: SharingSelector) -> SelectorResolution:
    """Route an atomic selector to its owning service."""
    if selector.kind in _CTF_KINDS:
        from ctf.services import resolve_model_access_selector as resolve_ctf_selector

        return resolve_ctf_selector(actor, selector)
    if selector.kind is SelectorKind.SELECTED_RANGES:
        return _resolve_selected(actor, selector)
    from cms.services import resolve_model_access_selector as resolve_cms_selector

    return resolve_cms_selector(actor, selector)


def resolve_model_access_selector(
    actor: object,
    selector: SharingSelector | dict[str, object],
) -> SelectorResolution:
    """Resolve an atomic selector or a bounded, non-recursive named union."""
    from cms.services import ModelAccessSelectorError as CmsModelAccessSelectorError
    from ctf.services import ModelAccessSelectorError as CtfModelAccessSelectorError

    try:
        parsed = selector if isinstance(selector, SharingSelector) else SharingSelector.model_validate(selector)
        if parsed.kind is not SelectorKind.NAMED_COLLECTION:
            return _resolve_atom(actor, parsed)
        return _combine(
            parsed,
            tuple(_resolve_atom(actor, member) for member in parsed.members),
            preserve_atomic_digests=True,
        )
    except ModelAccessCompositionError:
        raise
    except (
        CmsModelAccessSelectorError,
        CtfModelAccessSelectorError,
        ValidationError,
        ValueError,
    ) as exc:
        raise ModelAccessCompositionError(_SELECTOR_DENIED) from exc


def _publisher_identity(actor: object) -> OwnedReference:
    """Return the canonical user or operator identity for a publisher."""
    from management.services import is_platform_operator

    actor_id = getattr(actor, "pk", None)
    if isinstance(actor_id, bool) or not isinstance(actor_id, int) or actor_id <= 0:
        raise ModelAccessCompositionError(_SELECTOR_DENIED)
    noun = "operator" if is_platform_operator(actor) else "user"
    return OwnedReference(owner="management", reference=f"{noun}:{actor_id}")


def publish_model_access_binding(
    *,
    actor: object,
    deployment_id: UUID,
    catalog: ModelAccessCatalog,
    binding: SharingBinding,
    pool: SharingPool,
    expected_definition_revision: int,
    empty_snapshot_ack: bool = False,
) -> dict[str, object]:
    """Resolve, project, and publish one binding in a single DB transaction.

    Returns a bounded revision projection (binding id, definition revision, state);
    the raw Engine revision row never crosses the composition-root boundary.
    """
    from cms.services import (
        engine_fence_model_policy_publication,
        engine_project_selector_resolution,
        engine_publish_sharing_binding,
    )

    publisher = _publisher_identity(actor)
    now = timezone.now()
    with transaction.atomic():
        resolution = resolve_model_access_selector(actor, binding.selector)
        engine_fence_model_policy_publication(deployment_id)
        projection = engine_project_selector_resolution(
            deployment_id=deployment_id,
            sharing_binding_id=binding.sharing_binding_id,
            publisher_identity=publisher,
            resolution=resolution,
            observed_at=now,
            freshness_deadline=now + timedelta(minutes=5),
        )
        payload = binding.model_dump(mode="json")
        payload["membership_revision"] = projection.membership_revision
        projected_binding = seal_sharing_binding(payload)
        revision = engine_publish_sharing_binding(
            deployment_id=deployment_id,
            catalog=catalog,
            binding=projected_binding,
            pool=pool,
            publisher_identity=publisher,
            expected_definition_revision=expected_definition_revision,
            empty_snapshot_ack=empty_snapshot_ack,
        )
        return {
            "sharing_binding_id": projected_binding.sharing_binding_id,
            "definition_revision": revision.definition_revision,
            "state": revision.state,
        }


def drain_model_access_binding(
    *,
    actor: object,
    deployment_id: UUID,
    sharing_binding_id: str,
    expected_definition_revision: int,
) -> dict[str, object]:
    """Withdraw one binding as the resolved server-side publisher under a CAS fence.

    The publisher identity is derived from the authenticated actor, never trusted
    from the request. Engine rechecks publisher authority and the expected
    definition revision, tombstones the binding, and advances the membership
    fence; it never refunds, resets or cancels a billable request. Returns a
    bounded revision projection.
    """
    from cms.services import engine_drain_sharing_binding

    publisher = _publisher_identity(actor)
    revision = engine_drain_sharing_binding(
        deployment_id=deployment_id,
        sharing_binding_id=sharing_binding_id,
        publisher_identity=publisher,
        expected_definition_revision=expected_definition_revision,
    )
    return {
        "sharing_binding_id": sharing_binding_id,
        "definition_revision": revision.definition_revision,
        "state": revision.state,
    }
