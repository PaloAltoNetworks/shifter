"""Centralized user-type to CTF-group synchronization.

Single home for turning a (self-mutable) ``custom:user_type`` claim or a
dev-login selection into Django CTF group membership, callable by Cognito OIDC,
GCP Identity Platform, and dev-login. Every resulting change is recorded in a
durable, fail-closed audit row — the safety control that makes the self-mutable
attribute acceptable (issue #937 SEC-5).

Only the participant CTF group is reachable here by design (issue #1516): a
self-mutable ``user_type`` claim may grant ``CTF Participant`` but never
``CTF Organizer``, the ``Threat Research`` group, or Django ``is_staff`` /
``is_superuser``. Organizer authority is administrator-controlled and granted
only from verified provider evidence or explicit local assignment (see
:mod:`config.organizer_authority`); platform elevation stays env-email driven
via :func:`config.bootstrap_admin.apply_bootstrap_admin_flags`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.models import Group
from django.db import transaction

from management.services import get_user_profile, set_active_ctf_event
from shared.audit import (
    AuditActorType,
    RequestAudit,
    StateChange,
    audit_role_sync,
    get_client_ip,
    get_request_id,
)
from shared.auth import CTF_PARTICIPANT_GROUP

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.http import HttpRequest

logger = logging.getLogger(__name__)

# Self-service user_type values recognized on this path. ``ctf_organizer`` is
# intentionally absent (issue #1516): organizer authority must never be derivable
# from self-mutable identity/profile data. A ``ctf_organizer`` claim is treated as
# unrecognized and ignored here; the legacy value may still exist on stored
# profiles but grants nothing.
VALID_CTF_USER_TYPES = frozenset({"standard", "ctf_participant"})

# Single source of truth: user_type -> the one CTF group it grants (None grants
# no CTF group). Only the participant group is self-service reachable by design
# (issue #1516 / #937 SEC-5); ``CTF Organizer``, platform groups (Threat
# Research), and Django admin flags are never reachable from a self-asserted
# claim. Adding a future participant-only CTF role is a one-line change here plus
# a test, while organizer and platform elevation stay structurally out of reach.
USER_TYPE_TO_GROUP: dict[str, str | None] = {
    "standard": None,
    "ctf_participant": CTF_PARTICIPANT_GROUP,
}

# The CTF groups this self-service sync manages. Scoped to the participant group
# only so the self-service path never adds OR removes the administrator-
# controlled ``CTF Organizer`` group: a ``standard`` claim clears participant
# membership but leaves any admin-granted organizer group intact (issue #1516).
_SELF_SERVICE_CTF_GROUPS = (CTF_PARTICIPANT_GROUP,)


def _ctf_group_names(user: User) -> set[str]:
    """Return the user's current self-service-managed CTF group names."""
    return set(user.groups.filter(name__in=_SELF_SERVICE_CTF_GROUPS).values_list("name", flat=True))


def _request_context(request: HttpRequest | None) -> RequestAudit:
    """Return the request-derived audit context for the role-sync row."""
    if request is None:
        return RequestAudit()
    return RequestAudit(
        source_ip=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        request_id=get_request_id(request),
    )


def _sync_active_ctf_event(user: User, user_type: str, ctf_event_id: str | None) -> None:
    """Set the active CTF event for a participant when a valid event id is given."""
    if not ctf_event_id or user_type != "ctf_participant":
        return
    try:
        event_uuid = UUID(ctf_event_id)
    except (ValueError, TypeError):
        logger.warning("Invalid ctf_event_id for user %s, ignoring", getattr(user, "pk", None))
        return

    from ctf.services import event_pk_if_exists

    event_pk = event_pk_if_exists(event_uuid)
    if event_pk is not None:
        set_active_ctf_event(user, event_pk)
    else:
        logger.warning("CTF event %s not found for user %s", event_uuid, getattr(user, "pk", None))


def sync_user_type(
    user: User,
    claimed_user_type: str | None,
    *,
    source: str,
    request: HttpRequest | None = None,
    actor_type: str = AuditActorType.USER,
    ctf_event_id: str | None = None,
) -> None:
    """Align a user's CTF group membership and profile with ``claimed_user_type``.

    No-ops (and writes no audit row) when the claim is absent, unrecognized, or
    already satisfied. On a real change, updates CTF membership (a role claim adds
    its group and preserves any other CTF group; ``standard`` drops all CTF
    groups), syncs ``profile.user_type``, and writes a fail-closed ROLE_SYNC audit
    row — all inside one transaction so a failed audit rolls back the mutation it
    describes.

    Args:
        user: The saved Django user to update.
        claimed_user_type: The self-asserted user type (``standard`` /
            ``ctf_participant`` / ``ctf_organizer``); other values are ignored.
        source: Short provenance string for the audit row (e.g. ``"oidc"``).
        request: Optional HTTP request for source IP / user agent / request id.
        actor_type: Audit actor type; defaults to the subject user (self-service).
        ctf_event_id: Optional active CTF event id to sync for participants.
    """
    if claimed_user_type is None:
        return
    if claimed_user_type not in VALID_CTF_USER_TYPES:
        logger.warning(
            "Ignoring unrecognized user_type claim from %s for user %s",
            source,
            getattr(user, "pk", None),
        )
        return

    target_group = USER_TYPE_TO_GROUP[claimed_user_type]

    profile = get_user_profile(user)
    old_user_type = profile.user_type
    old_groups = _ctf_group_names(user)

    # Within the self-service-managed scope (participant group only, #1516):
    # ``standard`` drops participant membership; a participant claim ADDS the
    # participant group. Any admin-granted ``CTF Organizer`` group is outside this
    # scope and is never added or removed here.
    new_groups = set() if target_group is None else old_groups | {target_group}

    if new_groups != old_groups or old_user_type != claimed_user_type:
        request_audit = _request_context(request)
        with transaction.atomic():
            to_remove = old_groups - new_groups
            if to_remove:
                user.groups.remove(*Group.objects.filter(name__in=to_remove))
            for name in sorted(new_groups - old_groups):
                group, _ = Group.objects.get_or_create(name=name)
                user.groups.add(group)

            if old_user_type != claimed_user_type:
                profile.user_type = claimed_user_type
                profile.save(update_fields=["user_type"])

            audit_role_sync(
                user_id=user.id,
                actor_type=actor_type,
                actor_id=user.id,
                change=StateChange(
                    previous={"user_type": old_user_type, "groups": sorted(old_groups)},
                    new={"user_type": claimed_user_type, "groups": sorted(new_groups)},
                ),
                source=source,
                request=request_audit,
            )

    _sync_active_ctf_event(user, claimed_user_type, ctf_event_id)
