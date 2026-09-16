"""CMS-owned correlation between CMS range instances and Engine range identities."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.db import transaction
from pydantic import ValidationError

from cms.exceptions import CMSError
from cms.models import RangeInstance
from engine.services import SharingError
from shared.enums import ResourceStatus
from shared.model_access import (
    EligibilityBasis,
    ModelAccessRangeInstanceView,
    ModelAccessRangeView,
    OwnedReference,
    PublisherAuthorityRequirement,
    PublisherAuthorityScope,
    ResolvedSpendingEligibility,
    ResolvedSubjectAuthority,
    SelectorKind,
    SelectorResolution,
    SharingSelector,
    compute_digest,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User


class ModelAccessSelectorError(CMSError):
    """Opaque failure to resolve an exact CMS model-access range correlation."""

    code = "model_access.selector_denied"

    def __init__(self) -> None:
        super().__init__("Model-access selector denied")


def _normalized_range_instance_ids(range_instance_ids: tuple[int, ...]) -> tuple[int, ...]:
    """Validate explicit CMS range-instance identifiers in canonical order."""
    normalized = tuple(sorted(range_instance_ids))
    invalid = (
        len(normalized) > 1000
        or len(normalized) != len(set(normalized))
        or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in normalized)
    )
    if invalid:
        raise ModelAccessSelectorError()
    return normalized


def resolve_model_access_range_views(
    *,
    range_uuids: tuple[UUID, ...] | None = None,
    user_ids: tuple[int, ...] | None = None,
    workspace_ids: tuple[int, ...] | None = None,
    all_ranges: bool = False,
) -> tuple[ModelAccessRangeView, ...]:
    """Expose the exact Engine range query through the CMS service boundary."""
    from cms import services as cms_services

    try:
        return cms_services.engine_resolve_model_access_range_views(
            range_uuids=range_uuids,
            user_ids=user_ids,
            workspace_ids=workspace_ids,
            all_ranges=all_ranges,
        )
    except SharingError as exc:
        raise ModelAccessSelectorError() from exc


def resolve_model_access_range_instances(
    range_instance_ids: tuple[int, ...],
) -> tuple[ModelAccessRangeView, ...]:
    """Map exact active CMS range-instance PKs to canonical Engine identities."""
    from cms import services as cms_services

    normalized = _normalized_range_instance_ids(range_instance_ids)
    if not normalized:
        return ()

    with transaction.atomic():
        rows = tuple(
            RangeInstance.objects.select_for_update(of=("self",))
            .filter(pk__in=normalized)
            .exclude(status=ResourceStatus.DESTROYING.value)
            .select_related("request")
            .order_by("pk")
        )
        if len(rows) != len(normalized) or any(row.request_id is None for row in rows):
            raise ModelAccessSelectorError()
        request_uuids = tuple(row.request.request_id for row in rows)
        if len(request_uuids) != len(set(request_uuids)):
            raise ModelAccessSelectorError()
        try:
            engine_views = cms_services.engine_resolve_model_access_range_views(request_uuids=request_uuids)
        except SharingError as exc:
            raise ModelAccessSelectorError() from exc
        by_request = {item.request_uuid: item for item in engine_views}
        if set(by_request) != set(request_uuids):
            raise ModelAccessSelectorError()
        return tuple(by_request[request_uuid] for request_uuid in request_uuids)


def find_model_access_selected_ranges(
    range_uuids: tuple[UUID, ...],
) -> tuple[ModelAccessRangeInstanceView, ...]:
    """Find active CMS correlation records for a validated Engine range set."""
    from cms import services as cms_services

    normalized = tuple(sorted(range_uuids))
    if not normalized or len(normalized) > 1000 or len(normalized) != len(set(normalized)):
        raise ModelAccessSelectorError()
    with transaction.atomic():
        try:
            engine_views = cms_services.engine_resolve_model_access_range_views(range_uuids=normalized)
        except SharingError as exc:
            raise ModelAccessSelectorError() from exc
        request_uuids = tuple(item.request_uuid for item in engine_views if item.request_uuid is not None)
        instances = tuple(
            RangeInstance.objects.select_for_update(of=("self",))
            .filter(request__request_id__in=request_uuids)
            .exclude(status=ResourceStatus.DESTROYING.value)
            .select_related("request")
            .order_by("pk")
        )
        instance_by_request = {item.request.request_id: item for item in instances}
        if len(instance_by_request) != len(instances):
            raise ModelAccessSelectorError()
        return tuple(
            ModelAccessRangeInstanceView(
                range_instance_id=instance_by_request[item.request_uuid].pk,
                range_view=item,
            )
            for item in engine_views
            if item.request_uuid in instance_by_request
        )


def resolve_model_access_selected_ranges(
    range_uuids: tuple[UUID, ...],
) -> tuple[ModelAccessRangeInstanceView, ...]:
    """Resolve exact Engine UUIDs to active CMS instance correlation records."""
    resolved = find_model_access_selected_ranges(range_uuids)
    if len(resolved) != len(range_uuids):
        raise ModelAccessSelectorError()
    return resolved


def _integer_ids(values: tuple[str, ...]) -> tuple[int, ...]:
    """Parse canonical positive integer selector identifiers."""
    try:
        resolved = tuple(int(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ModelAccessSelectorError() from exc
    if any(value <= 0 or str(value) != supplied for value, supplied in zip(resolved, values, strict=True)):
        raise ModelAccessSelectorError()
    return resolved


def _uuid_ids(values: tuple[str, ...]) -> tuple[UUID, ...]:
    """Parse canonical UUID selector identifiers."""
    try:
        resolved = tuple(UUID(value) for value in values)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ModelAccessSelectorError() from exc
    if any(str(value) != supplied for value, supplied in zip(resolved, values, strict=True)):
        raise ModelAccessSelectorError()
    return resolved


def _publisher_requirement(
    selector_digest: str,
    authority_ref: OwnedReference,
    *,
    scope: PublisherAuthorityScope = PublisherAuthorityScope.SELECTOR,
) -> PublisherAuthorityRequirement:
    """Build one selector-digest-bound publisher authority requirement."""
    return PublisherAuthorityRequirement(
        selector_digest=selector_digest,
        authority_ref=authority_ref,
        scope=scope,
    )


def _resolution(
    selector: SharingSelector,
    ranges: Iterable[ModelAccessRangeView],
    *,
    selector_refs: tuple[OwnedReference, ...],
    subject_authority_by_range: dict[UUID, OwnedReference],
    publisher_requirements: tuple[PublisherAuthorityRequirement, ...],
    spending: tuple[ResolvedSpendingEligibility, ...] = (),
) -> SelectorResolution:
    """Build a canonical selector resolution from resolved Engine ranges."""
    range_views = tuple(ranges)
    return SelectorResolution(
        contract_version="model-access-selector-resolution/v1",
        selector_digest=compute_digest(selector),
        assessment_count=len(range_views),
        member_refs=tuple(item.range_ref for item in range_views),
        selector_authority_refs=selector_refs,
        subject_authorities=tuple(
            ResolvedSubjectAuthority(
                subject_ref=item.range_ref,
                authority_ref=subject_authority_by_range[item.range_uuid],
            )
            for item in range_views
        ),
        publisher_requirements=publisher_requirements,
        spending_eligibilities=spending,
    )


def _operator_ref(actor: object) -> OwnedReference:
    """Build the canonical operator reference for an authenticated actor."""
    return OwnedReference(owner="management", reference=f"operator:{getattr(actor, 'pk', 0)}")


def _resolve_selected(actor: object, selector: SharingSelector) -> SelectorResolution:
    """Resolve explicit ordinary ranges under owner or operator authority."""
    from management.services import is_platform_operator

    ranges = resolve_model_access_range_views(range_uuids=_uuid_ids(selector.ids))
    is_operator = is_platform_operator(actor)
    actor_id = getattr(actor, "pk", None)
    if not is_operator and any(item.owner_user_id != actor_id for item in ranges):
        raise ModelAccessSelectorError()
    digest = compute_digest(selector)
    publisher_refs = (_operator_ref(actor),) if is_operator else tuple(item.authority_ref for item in ranges)
    return _resolution(
        selector,
        ranges,
        selector_refs=tuple(item.authority_ref for item in ranges),
        subject_authority_by_range={item.range_uuid: item.authority_ref for item in ranges},
        publisher_requirements=tuple(_publisher_requirement(digest, item) for item in publisher_refs),
    )


def _resolve_users(actor: object, selector: SharingSelector) -> SelectorResolution:
    """Resolve a user selector through identity and range owner services."""
    from management.services import is_platform_operator, resolve_model_access_users

    user_ids = resolve_model_access_users(actor, _integer_ids(selector.ids))
    ranges = resolve_model_access_range_views(user_ids=user_ids)
    digest = compute_digest(selector)
    refs = tuple(OwnedReference(owner="management", reference=f"user:{user_id}") for user_id in user_ids)
    ref_by_user = dict(zip(user_ids, refs, strict=True))
    publisher_ref = _operator_ref(actor) if is_platform_operator(actor) else refs[0]
    return _resolution(
        selector,
        ranges,
        selector_refs=refs,
        subject_authority_by_range={item.range_uuid: ref_by_user[item.owner_user_id] for item in ranges},
        publisher_requirements=(_publisher_requirement(digest, publisher_ref),),
    )


def _resolve_groups(actor: object, selector: SharingSelector) -> SelectorResolution:
    """Resolve auth-group membership with explicit funded eligibility."""
    from management.services import resolve_model_access_group

    scopes = tuple(resolve_model_access_group(actor, group_id) for group_id in _integer_ids(selector.ids))
    user_ids = tuple(sorted({user_id for scope in scopes for user_id in scope.user_ids}))
    ranges = resolve_model_access_range_views(user_ids=user_ids)
    group_refs = tuple(OwnedReference(owner="management", reference=f"auth-group:{scope.group_id}") for scope in scopes)
    user_refs = tuple(OwnedReference(owner="management", reference=f"user:{user_id}") for user_id in user_ids)
    user_authorities = dict(zip(user_ids, user_refs, strict=True))
    spending = tuple(
        ResolvedSpendingEligibility(
            authority_ref=group_refs[index],
            basis=EligibilityBasis(scope.eligibility_basis),
        )
        for index, scope in enumerate(scopes)
        if scope.eligibility_basis is not None
    )
    return _resolution(
        selector,
        ranges,
        selector_refs=group_refs + user_refs,
        subject_authority_by_range={item.range_uuid: user_authorities[item.owner_user_id] for item in ranges},
        publisher_requirements=(_publisher_requirement(compute_digest(selector), _operator_ref(actor)),),
        spending=spending,
    )


def _resolve_workspaces(actor: object, selector: SharingSelector) -> SelectorResolution:
    """Resolve workspace membership through workspace-owned authority."""
    from workspaces.services import resolve_model_access_workspace

    user = cast("User", actor)
    scopes = tuple(resolve_model_access_workspace(user, workspace_uuid) for workspace_uuid in _uuid_ids(selector.ids))
    ranges = resolve_model_access_range_views(workspace_ids=tuple(scope.workspace_id for scope in scopes))
    publisher_refs = tuple(OwnedReference(owner="workspaces", reference=scope.authority_reference) for scope in scopes)
    containment_refs = tuple(
        OwnedReference(owner="workspaces", reference=scope.containment_reference) for scope in scopes
    )
    refs_by_workspace = dict(zip((scope.workspace_id for scope in scopes), containment_refs, strict=True))
    digest = compute_digest(selector)
    return _resolution(
        selector,
        ranges,
        selector_refs=publisher_refs + containment_refs,
        subject_authority_by_range={item.range_uuid: refs_by_workspace[item.workspace_id] for item in ranges},
        publisher_requirements=tuple(_publisher_requirement(digest, item) for item in publisher_refs),
    )


def _resolve_organizations(actor: object, selector: SharingSelector) -> SelectorResolution:
    """Resolve organization workspaces through organization-owned authority."""
    from workspaces.services import resolve_model_access_organization

    user = cast("User", actor)
    scopes = tuple(
        resolve_model_access_organization(user, organization_uuid) for organization_uuid in _uuid_ids(selector.ids)
    )
    workspace_ids = tuple(sorted({item for scope in scopes for item in scope.workspace_ids}))
    ranges = resolve_model_access_range_views(workspace_ids=workspace_ids)
    organization_refs = tuple(
        OwnedReference(owner="workspaces", reference=scope.authority_reference) for scope in scopes
    )
    workspace_refs = tuple(
        OwnedReference(owner="workspaces", reference=f"workspace-id:{workspace_id}") for workspace_id in workspace_ids
    )
    workspace_ref_by_id = dict(zip(workspace_ids, workspace_refs, strict=True))
    refs_by_workspace = {
        workspace_id: workspace_ref_by_id[workspace_id] for scope in scopes for workspace_id in scope.workspace_ids
    }
    digest = compute_digest(selector)
    return _resolution(
        selector,
        ranges,
        selector_refs=organization_refs + workspace_refs,
        subject_authority_by_range={item.range_uuid: refs_by_workspace[item.workspace_id] for item in ranges},
        publisher_requirements=tuple(_publisher_requirement(digest, item) for item in organization_refs),
    )


def _resolve_all_ranges(actor: object, selector: SharingSelector) -> SelectorResolution:
    """Resolve the deployment-wide selector for a platform operator."""
    from management.services import is_platform_operator

    if not is_platform_operator(actor):
        raise ModelAccessSelectorError()
    ranges = resolve_model_access_range_views(all_ranges=True)
    selector_ref = OwnedReference(owner="engine", reference="all-ranges")
    return _resolution(
        selector,
        ranges,
        selector_refs=(selector_ref,),
        subject_authority_by_range={item.range_uuid: item.authority_ref for item in ranges},
        publisher_requirements=(
            _publisher_requirement(
                compute_digest(selector),
                _operator_ref(actor),
                scope=PublisherAuthorityScope.DEPLOYMENT,
            ),
        ),
    )


_RESOLVERS = {
    SelectorKind.SELECTED_RANGES: _resolve_selected,
    SelectorKind.USER: _resolve_users,
    SelectorKind.AUTH_GROUP: _resolve_groups,
    SelectorKind.WORKSPACE: _resolve_workspaces,
    SelectorKind.ORGANIZATION: _resolve_organizations,
    SelectorKind.ALL_RANGES: _resolve_all_ranges,
}


def resolve_model_access_selector(actor: object, selector: SharingSelector | dict[str, object]) -> SelectorResolution:
    """Resolve one non-CTF atomic selector through its owning service boundaries."""
    from management.services import ModelAccessIdentityAuthorityError
    from workspaces.services import OrganizationAuthorizationError, WorkspaceAuthorizationError

    try:
        parsed = selector if isinstance(selector, SharingSelector) else SharingSelector.model_validate(selector)
        resolver = _RESOLVERS.get(parsed.kind)
        if resolver is None:
            raise ModelAccessSelectorError()
        return resolver(actor, parsed)
    except ModelAccessSelectorError:
        raise
    except (
        ModelAccessIdentityAuthorityError,
        OrganizationAuthorizationError,
        SharingError,
        WorkspaceAuthorizationError,
    ) as exc:
        raise ModelAccessSelectorError() from exc
    except ValidationError as exc:
        raise ModelAccessSelectorError() from exc
