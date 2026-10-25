"""Prepared policy offboarding composes the incumbent domain ownership writers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.db import IntegrityError, transaction

from cms.exceptions import CMSError
from cms.models import RangeInstance, Request
from engine.services import RangeOwnershipProjection, RangeProjectionIntegrityError, range_ownership_projection
from shared.audit import AuditAction, AuditEntityType, AuditEvent, RequestAudit, audit_log
from shared.authorization import AuthorizationProvider, AuthorizationRequest, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef, ResourceScope
from shared.principal_port import principal_for_user, principal_identity_for_user, resolve_principal
from workspaces.services import (
    AccountScopeError,
    WorkspaceOwnershipCandidate,
    admin_transfer_workspace_principal,
    policy_owned_workspace_candidates,
    resource_scope_from_ids,
    scope_has_principal_member,
)

from ._range_reassign import _is_active_range_conflict, _reassign_range_owner_locked
from ._user_offboarding import TRANSFERABLE_RESOURCE_KINDS, OwnershipTransferSummary

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.contrib.auth.models import User

_OWNERSHIP_PROJECTIONS_DISAGREE = "Range ownership projections disagree"


def _require(
    actor: CredentialContext, provider: AuthorizationProvider, action: str, target: TargetRef, scope: ResourceScope
) -> None:
    """Shared policy is the sole grant; evaluator failures never become success."""
    try:
        if actor.kind == "temporary":
            raise PermissionError
        resolve_principal(actor.principal)
        if not provider.check(AuthorizationRequest(actor.principal, action, target, scope, actor.ceiling)).allowed:
            raise PermissionError
    except Exception as exc:
        raise PermissionError("Ownership transfer denied") from exc


def _ancestry(
    row: RangeInstance | Request | RangeOwnershipProjection,
) -> tuple[str, int | None, int | None, int | None]:
    """Compare the same persisted ancestry across the owning projections."""
    return row.scope_kind, row.account_id, row.organization_id, row.workspace_id


def _checked_projection(instance: RangeInstance) -> RangeOwnershipProjection:
    """Read Engine correlation and reject any disagreement before admission."""
    if instance.request is None:
        raise CMSError("Range ownership unavailable")
    projection = range_ownership_projection(instance.request.request_id)
    if (
        projection is None
        or _ancestry(instance) != _ancestry(instance.request)
        or _ancestry(instance) != _ancestry(projection)
    ):
        raise CMSError(_OWNERSHIP_PROJECTIONS_DISAGREE)
    return projection


def policy_reassign_range_owner(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    instance_uuid: UUID,
    destination: User,
    *,
    expected_owner_id: int | None = None,
    audit: RequestAudit | None = None,
) -> None:
    """Authorize the persistent source and an eligible same-scope destination."""
    instance = (
        RangeInstance.objects.select_related("request").filter(uuid=instance_uuid, deleted_at__isnull=True).first()
    )
    if instance is None or instance.request is None:
        raise CMSError("Range ownership unavailable")
    if expected_owner_id is not None and instance.user_id != expected_owner_id:
        raise CMSError("Range ownership changed")
    projection = _checked_projection(instance)
    scope = resource_scope_from_ids(
        kind=instance.scope_kind,
        account_id=instance.account_id,
        organization_id=instance.organization_id,
        workspace_id=instance.workspace_id,
    )
    _require(actor, provider, "range.transfer_ownership", TargetRef("range", projection.uuid), scope)
    destination_ref = principal_for_user(destination)
    expected_owner = instance.user_id if expected_owner_id is None else expected_owner_id
    if not (
        instance.request.user_id
        == projection.user_id
        == projection.cms_user_id
        == projection.request_user_id
        == expected_owner
    ):
        raise CMSError(_OWNERSHIP_PROJECTIONS_DISAGREE)
    attribution = audit or RequestAudit()
    try:
        _transfer_locked(actor, instance, destination, destination_ref, scope, expected_owner, attribution)
    except IntegrityError as exc:
        if _is_active_range_conflict(exc):
            raise CMSError("Replacement already owns an active range for this source") from exc
        raise


def _transfer_locked(
    actor: CredentialContext,
    instance: RangeInstance,
    destination: User,
    destination_ref: PrincipalRef,
    scope: ResourceScope,
    expected_owner: int | None,
    attribution: RequestAudit,
) -> None:
    """Keep the named collision translation outside the resource transaction."""
    with transaction.atomic():
        # Recheck eligibility and ownership under the incumbent mutexes. The
        # provider check above remains outside these SQL locks.
        if not scope_has_principal_member(scope, destination_ref, lock=True):
            raise CMSError("Replacement is not eligible for the resource scope")
        current = RangeInstance.objects.select_for_update().get(pk=instance.pk)
        request = Request.objects.select_for_update().get(pk=instance.request_id)
        if (
            current.user_id != expected_owner
            or request.user_id != expected_owner
            or _ancestry(current) != _ancestry(instance)
            or _ancestry(request) != _ancestry(instance)
        ):
            raise CMSError(_OWNERSHIP_PROJECTIONS_DISAGREE)
        current.request = request
        try:
            _reassign_range_owner_locked(
                current, destination, expected_owner_id=expected_owner, expected_scope=_ancestry(instance)
            )
        except RangeProjectionIntegrityError as exc:
            raise CMSError(_OWNERSHIP_PROJECTIONS_DISAGREE) from exc
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=current.pk,
                action=AuditAction.UPDATE,
                actor_type="principal",
                actor_principal_uuid=actor.principal.uuid,
                previous_state={"user_id": expected_owner},
                new_state={"user_id": destination.pk},
                context="range ownership offboarding transfer",
                source_ip=attribution.source_ip,
                user_agent=attribution.user_agent[:500],
                request_id=attribution.request_id[:64],
            ),
            strict=True,
        )


def policy_transfer_user_ownership(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    source: User,
    destination: User,
    *,
    kinds: Iterable[str],
    audit: RequestAudit | None = None,
) -> OwnershipTransferSummary:
    """Offboard an inactive human through a service or human administrator.

    Each successful resource effect is transactional. The summary retains
    blocked outcomes and makes no claim of a globally atomic offboarding.
    """
    _require(
        actor, provider, "installation.manage_principals", TargetRef("installation"), ResourceScope("installation")
    )
    requested = tuple(dict.fromkeys(kinds))
    if (
        not requested
        or any(kind not in TRANSFERABLE_RESOURCE_KINDS for kind in requested)
        or source.pk == destination.pk
    ):
        raise ValueError("Invalid ownership transfer")
    source_ref = principal_identity_for_user(source)
    destination_ref = principal_for_user(destination)
    workspace_plan = (
        policy_owned_workspace_candidates(actor, provider, source_ref.uuid, destination_ref.uuid)
        if "workspaces" in requested
        else ()
    )
    range_ids = (
        tuple(
            RangeInstance.objects.filter(user_id=source.pk, deleted_at__isnull=True)
            .order_by("pk")
            .values_list("uuid", flat=True)[:1001]
        )
        if "ranges" in requested
        else ()
    )
    if len(range_ids) > 1000:
        raise PermissionError("Ownership transfer unavailable")
    transferred, blocked_workspaces, blocked_membership = _transfer_workspace_candidates(
        actor, provider, source_ref.uuid, destination_ref.uuid, workspace_plan, audit
    )
    reassigned, blocked_ranges = _transfer_range_candidates(actor, provider, source, destination, range_ids, audit)
    return OwnershipTransferSummary(
        ranges_reassigned=reassigned,
        ranges_blocked=blocked_ranges,
        workspaces_transferred=transferred,
        workspaces_blocked_no_membership=blocked_membership,
        workspaces_blocked=blocked_workspaces,
    )


def _transfer_workspace_candidates(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    source_uuid: UUID,
    destination_uuid: UUID,
    workspace_plan: Iterable[WorkspaceOwnershipCandidate],
    audit: RequestAudit | None,
) -> tuple[int, int, int]:
    """Keep resource rejection counts separate from independently committed successes."""
    transferred = blocked_workspaces = blocked_membership = 0
    for candidate in workspace_plan:
        if candidate.blocked_reason is not None:
            blocked_workspaces += 1
            blocked_membership += int(candidate.blocked_reason == "no_membership")
            continue
        try:
            admin_transfer_workspace_principal(
                actor, provider, candidate.workspace_uuid, source_uuid, destination_uuid, audit=audit
            )
        except AccountScopeError:
            blocked_workspaces += 1
        else:
            transferred += 1
    return transferred, blocked_workspaces, blocked_membership


def _transfer_range_candidates(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    source: User,
    destination: User,
    range_ids: Iterable[UUID],
    audit: RequestAudit | None,
) -> tuple[int, int]:
    """Aggregate only known resource rejections; unexpected failures still propagate."""
    reassigned = blocked_ranges = 0
    for instance_uuid in range_ids:
        try:
            policy_reassign_range_owner(
                actor, provider, instance_uuid, destination, expected_owner_id=source.pk, audit=audit
            )
        except (AccountScopeError, CMSError, PermissionError, RangeProjectionIntegrityError):
            blocked_ranges += 1
        else:
            reassigned += 1
    return reassigned, blocked_ranges
