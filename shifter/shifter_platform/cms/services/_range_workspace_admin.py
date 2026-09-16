"""Range-to-workspace scope administration (PLAT-237, #1944).

CMS is the only layer permitted to consume both ``workspaces.services`` and
``engine.services`` (ADR-001), so the administrative "list ranges scoped to a
workspace" query and the "reassign a range's workspace scope" command live here
rather than at the composition root or in a view.

The command administers exactly one existing fact -- the scalar ``workspace_id``
copied from CMS request intent to the CMS range projection and the Engine range
(ADR-046). It never changes the range's individual owner, lifecycle, source,
lease, or access semantics, and it introduces no cross-layer ForeignKey.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from cms.exceptions import RangeScopeAdminError
from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from engine.services import (
    RangeProjectionIntegrityError,
    RangeWorkspaceRebindOutcome,
    rebind_range_workspace_by_request,
)
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from shared.log_sanitize import safe_log_value
from shared.range_workspace_aggregate import range_in_domain_aggregate
from workspaces.services import (
    WorkspaceAuthorizationError,
    WorkspaceOperation,
    authorize_bound_workspace,
    authorize_range_rebind,
    authorize_workspace,
)

from ._common import _validate_caller_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import QuerySet

logger = logging.getLogger(__name__)

# Reused opaque outcome messages (Sonar S1192: no duplicated literals). Both are
# deliberately non-enumerating.
_RANGE_NOT_FOUND = "Range not found"
_PROJECTION_INCONSISTENT = "Range projection is inconsistent"


@dataclass(frozen=True, slots=True)
class RangeScopeAuditContext:
    """Request attribution for a scope-rebind audit event, supplied by the caller."""

    actor_type: str
    actor_id: int | None
    request_id: str = ""
    source_ip: str | None = None
    user_agent: str = ""


@dataclass(frozen=True, slots=True)
class RangeRebindResult:
    """Bounded, secret-free result of a range workspace scope reassignment."""

    changed: bool


def list_range_scope_bindings(actor: User, *, workspace_uuid: str | uuid.UUID) -> QuerySet[RangeInstance]:
    """Return the ranges scoped to ``workspace_uuid`` for administrative display.

    Authorizes ``actor`` for ``LIST_RANGE_SCOPE_BINDINGS`` in the workspace named
    by its public UUID, then returns an ordered queryset of the workspace's range
    projections for the API to paginate and serialize. Administrative visibility
    only -- it never grants interactive range access. An unknown workspace and an
    unauthorized one share one opaque not-found outcome so the surface is not a
    tenant-enumeration oracle.

    Raises:
        RangeScopeAdminError: ``Kind.NOT_FOUND`` when the workspace is unknown or
            the actor may not administer its range scope.
    """
    _validate_caller_user(actor, "list_range_scope_bindings")

    try:
        authorization = authorize_workspace(actor, workspace_uuid, WorkspaceOperation.LIST_RANGE_SCOPE_BINDINGS)
    except WorkspaceAuthorizationError as exc:
        raise RangeScopeAdminError(RangeScopeAdminError.Kind.NOT_FOUND, "Workspace not found") from exc

    return (
        RangeInstance.objects.filter(workspace_id=authorization.workspace_id)
        .select_related("request")
        .order_by("-created_at", "-id")
    )


def _resolve_locked_range(request_id: uuid.UUID) -> tuple[RangeInstance, CmsRequest, int]:
    """Lock and uniquely resolve the CMS range projection + request for ``request_id``.

    Returns ``(range_instance, request, source_workspace_id)`` with both rows
    locked ``FOR UPDATE`` and the source scope confirmed consistent between them.
    Missing, duplicate, or disagreeing projections fail closed rather than let the
    move guess which row to touch.
    """
    instances = list(RangeInstance.objects.select_for_update().filter(request__request_id=request_id))
    if not instances:
        raise RangeScopeAdminError(RangeScopeAdminError.Kind.NOT_FOUND, _RANGE_NOT_FOUND)
    if len(instances) > 1:
        raise RangeScopeAdminError(RangeScopeAdminError.Kind.CONFLICT, _PROJECTION_INCONSISTENT)
    instance = instances[0]

    request = CmsRequest.objects.select_for_update().filter(request_id=request_id).first()
    if request is None or instance.request_id != request.id:
        raise RangeScopeAdminError(RangeScopeAdminError.Kind.NOT_FOUND, _RANGE_NOT_FOUND)

    source_workspace_id = instance.workspace_id
    if request.workspace_id != source_workspace_id:
        raise RangeScopeAdminError(RangeScopeAdminError.Kind.CONFLICT, "Range scope projections disagree")

    return instance, request, source_workspace_id


def rebind_range_workspace(
    actor: User,
    *,
    request_id: uuid.UUID,
    target_workspace_uuid: str | uuid.UUID,
    audit: RangeScopeAuditContext,
) -> RangeRebindResult:
    """Reassign a range's workspace scope from its current binding to a target.

    Addresses the range by its CMS ``Request.request_id`` correlation UUID and
    accepts only a target workspace public UUID; internal ids are never accepted
    from callers. In one transaction it locks and uniquely resolves the CMS
    Request, its range projection, and the correlated Engine range; verifies all
    three carry the same expected source; authorizes the move in both the source
    and target scopes under the workspace mutexes (with the unchanged owner's
    target membership); moves all three bindings with an expected-source
    compare-and-set; and writes a strict audit event -- or rolls everything back.

    Only ``workspace_id`` changes. Owner, source, lifecycle, lease, and access
    semantics are preserved. A target equal to the consistent current binding is
    an authorized idempotent no-op that emits no mutation audit. A range that
    participates in a domain-owned immutable aggregate (for example an ADR-051 CTF
    event) fails closed. Projection drift, duplicate projections, and concurrent
    moves fail closed rather than being silently repaired or overwritten.

    Raises:
        RangeScopeAdminError: With the classified :class:`RangeScopeAdminError.Kind`
            for every not-found, target-denied, conflict, and not-reassignable
            outcome.
    """
    _validate_caller_user(actor, "rebind_range_workspace")

    with transaction.atomic():
        instance, request, source_workspace_id = _resolve_locked_range(request_id)

        # Fail closed for domain-owned aggregates (ADR-046-R14). A range that a
        # domain (an ADR-051 CTF event, or a future aggregate) owns is bound to
        # that aggregate's workspace and cannot be moved independently. Membership
        # is decided authoritatively by the domain's registered guard through the
        # shared seam, never inferred from the range's provenance label: a range
        # can carry Mission Control provenance and still belong to an aggregate.
        if range_in_domain_aggregate(request_id, instance.pk):
            raise RangeScopeAdminError(
                RangeScopeAdminError.Kind.NOT_REASSIGNABLE,
                "This range's workspace scope cannot be reassigned",
            )

        # Source authority pre-check: an actor who cannot administer the range's
        # own scope sees the same opaque not-found as a missing range.
        try:
            authorize_bound_workspace(actor, source_workspace_id, WorkspaceOperation.REBIND_RANGE_WORKSPACE)
        except WorkspaceAuthorizationError as exc:
            raise RangeScopeAdminError(RangeScopeAdminError.Kind.NOT_FOUND, _RANGE_NOT_FOUND) from exc

        # Authoritative pair authorization under both workspace mutexes: rechecks
        # source authority, resolves + authorizes the target, rejects an archived
        # target, and requires the unchanged owner's membership in the target.
        try:
            authorization = authorize_range_rebind(
                actor,
                source_workspace_id=source_workspace_id,
                target_workspace_uuid=target_workspace_uuid,
                range_owner_id=instance.user_id,
            )
        except WorkspaceAuthorizationError as exc:
            raise RangeScopeAdminError(
                RangeScopeAdminError.Kind.TARGET_DENIED,
                "Target workspace is not eligible for this move",
            ) from exc

        target_workspace_id = authorization.target_workspace_id

        # Expected-source compare-and-set on the Engine range. This also verifies
        # three-way consistency: a missing engine range or a binding that is
        # neither the expected source nor the target is projection drift. A
        # duplicate Engine projection is a bounded integrity conflict, not a 500.
        try:
            outcome = rebind_range_workspace_by_request(
                request_id,
                expected_workspace_id=source_workspace_id,
                new_workspace_id=target_workspace_id,
            )
        except RangeProjectionIntegrityError as exc:
            raise RangeScopeAdminError(RangeScopeAdminError.Kind.CONFLICT, _PROJECTION_INCONSISTENT) from exc
        if outcome is RangeWorkspaceRebindOutcome.NOT_FOUND:
            raise RangeScopeAdminError(RangeScopeAdminError.Kind.CONFLICT, _PROJECTION_INCONSISTENT)
        if outcome is RangeWorkspaceRebindOutcome.SOURCE_MISMATCH:
            raise RangeScopeAdminError(RangeScopeAdminError.Kind.CONFLICT, "Range scope changed concurrently")

        if authorization.is_same_scope:
            # Target equals the consistent current binding: authorized idempotent
            # no-op. The engine returned UNCHANGED; no CMS write, no mutation audit.
            return RangeRebindResult(changed=False)

        if outcome is RangeWorkspaceRebindOutcome.UNCHANGED:
            # The engine range already carried the target while CMS still carried
            # the source: projection drift. Fail closed rather than repair it.
            raise RangeScopeAdminError(RangeScopeAdminError.Kind.CONFLICT, _PROJECTION_INCONSISTENT)

        # outcome is UPDATED: move the two CMS projections to match and audit.
        instance.workspace_id = target_workspace_id
        instance.save(update_fields=["workspace_id"])
        request.workspace_id = target_workspace_id
        request.save(update_fields=["workspace_id"])

        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=instance.pk,
                action=AuditAction.UPDATE,
                actor_type=audit.actor_type,
                actor_id=audit.actor_id,
                previous_state={"workspace_id": source_workspace_id},
                new_state={"workspace_id": target_workspace_id},
                context="range workspace scope reassignment",
                request_id=audit.request_id,
                source_ip=audit.source_ip,
                user_agent=audit.user_agent,
            ),
            strict=True,
        )
        logger.info(
            "rebind_range_workspace: request_id=%s moved workspace_id %s -> %s by actor_id=%s",
            safe_log_value(request_id),
            source_workspace_id,
            target_workspace_id,
            getattr(actor, "id", None),
        )
        return RangeRebindResult(changed=True)
