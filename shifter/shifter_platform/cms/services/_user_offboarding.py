"""Administrator user-offboarding ownership transfer orchestration (PLAT-236, #1943).

CMS is the only layer permitted to import both ``engine.services`` (via the
existing ``reassign_range_owner`` control-plane authority) and
``workspaces.services`` (ADR-001 layer contract), so the single bounded
offboarding transfer command lives here rather than at the composition root. The
composition-root Administer view calls this after resolving and authorizing the
source and replacement accounts.

Transfer is a *closed* per-kind manifest, never a wildcard or generic
``owner_id`` rewrite:

* ``workspaces`` delegates to :func:`workspaces.services.admin_transfer_workspace_ownership`
  (ADR-046-R13): every non-personal workspace the source owns moves to the
  replacement when the replacement already holds a membership.
* ``ranges`` delegates per range to :func:`cms.services.reassign_range_owner`,
  which preserves the CMS/Engine ownership projections, the new owner's workspace
  membership requirement, active-range uniqueness, and the live-VPN refusal.

Workspaces are transferred first so a replacement promoted to workspace owner
then satisfies the membership requirement for that workspace's ranges.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from cms.exceptions import CMSError
from cms.models import RangeInstance
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from workspaces.services import WorkspaceAuditContext, admin_transfer_workspace_ownership

from ._range_reassign import reassign_range_owner

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

#: The closed set of resource kinds an offboarding transfer may target.
TRANSFERABLE_RESOURCE_KINDS = ("ranges", "workspaces")


@dataclass(frozen=True, slots=True)
class OffboardingAuditContext:
    """Request attribution for an offboarding transfer, supplied by the caller."""

    actor_type: str
    actor_id: int | None
    request_id: str = ""
    source_ip: str | None = None
    user_agent: str = ""


@dataclass(frozen=True, slots=True)
class OwnershipTransferSummary:
    """Bounded, secret-free counts from an offboarding ownership transfer."""

    ranges_reassigned: int = 0
    ranges_blocked: int = 0
    workspaces_transferred: int = 0
    workspaces_already_owned: int = 0
    workspaces_blocked_no_membership: int = 0


def _transfer_ranges(source_user: User, replacement_user: User, audit: OffboardingAuditContext) -> tuple[int, int]:
    """Reassign the source user's active ranges; return ``(reassigned, blocked)``."""
    reassigned = blocked = 0
    instance_pks = list(
        RangeInstance.objects.filter(user_id=source_user.id, deleted_at__isnull=True).values_list("pk", flat=True)
    )
    for pk in instance_pks:
        try:
            with transaction.atomic():
                reassign_range_owner(pk, replacement_user)
                audit_log(
                    AuditEvent(
                        entity_type=AuditEntityType.RANGE,
                        entity_id=pk,
                        action=AuditAction.UPDATE,
                        actor_type=audit.actor_type,
                        actor_id=audit.actor_id,
                        previous_state={"user_id": source_user.id},
                        new_state={"user_id": replacement_user.id},
                        context="range ownership offboarding transfer",
                        request_id=audit.request_id,
                        source_ip=audit.source_ip,
                        user_agent=audit.user_agent,
                    ),
                    strict=True,
                )
            reassigned += 1
        except CMSError:
            # Blocked (new owner not a member of the range's workspace, an active
            # participant VPN credential, or an active-range conflict). Reported,
            # never forced.
            blocked += 1
    return reassigned, blocked


def _transfer_workspaces(source_user: User, replacement_user: User, audit: OffboardingAuditContext) -> tuple[int, int]:
    """Transfer the source user's owned workspaces; return ``(transferred, blocked)``."""
    results = admin_transfer_workspace_ownership(
        source_user_id=source_user.id,
        new_owner_user_id=replacement_user.id,
        audit=WorkspaceAuditContext(
            actor_type=audit.actor_type,
            actor_id=audit.actor_id,
            source_ip=audit.source_ip,
            user_agent=audit.user_agent,
            request_id=audit.request_id,
        ),
    )
    transferred = sum(1 for result in results if result.outcome == "transferred")
    blocked = sum(1 for result in results if result.outcome == "blocked_no_membership")
    return transferred, blocked


def transfer_user_ownership(
    source_user: User,
    replacement_user: User,
    *,
    kinds: Iterable[str],
    audit: OffboardingAuditContext,
) -> OwnershipTransferSummary:
    """Transfer a departing user's owned resources of the requested ``kinds``.

    ``kinds`` must be a subset of :data:`TRANSFERABLE_RESOURCE_KINDS`. Workspaces
    are transferred before ranges. Per-workspace audit is written by the
    workspaces service; the composition-root caller records the bounded summary.

    Raises:
        ValueError: If ``kinds`` contains an unknown resource kind.
    """
    # de-dupe while preserving order
    requested = list(dict.fromkeys(kinds))
    unknown = [kind for kind in requested if kind not in TRANSFERABLE_RESOURCE_KINDS]
    if unknown:
        raise ValueError(f"Unknown transfer resource kind(s): {', '.join(sorted(unknown))}")

    ws_transferred = ws_blocked = 0
    ranges_reassigned = ranges_blocked = 0
    if "workspaces" in requested:
        ws_transferred, ws_blocked = _transfer_workspaces(source_user, replacement_user, audit)
    if "ranges" in requested:
        ranges_reassigned, ranges_blocked = _transfer_ranges(source_user, replacement_user, audit)

    summary = OwnershipTransferSummary(
        ranges_reassigned=ranges_reassigned,
        ranges_blocked=ranges_blocked,
        workspaces_transferred=ws_transferred,
        workspaces_already_owned=0,
        workspaces_blocked_no_membership=ws_blocked,
    )
    logger.info(
        "transfer_user_ownership source_user_id=%s replacement_user_id=%s %s",
        source_user.id,
        replacement_user.id,
        summary,
    )
    return summary
