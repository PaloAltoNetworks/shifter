"""CTF live-repair and range-recovery audit helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from shared.audit import (
    AuditAction,
    AuditActorType,
    AuditEntityType,
    AuditEvent,
    audit_log,
    get_actor_from_request,
    get_client_ip,
    get_request_id,
)

if TYPE_CHECKING:
    from django.http import HttpRequest
    from rest_framework.request import Request

    from ctf.models import (
        CTFContentHydrationReceipt,
        CTFEvent,
        CTFParticipant,
        CTFRangeRecovery,
    )


def audit_platform_admin_event_action(
    *,
    request: Request | HttpRequest,
    event: CTFEvent,
    operation: str,
    effective_actor_id: int | None,
    action: str = AuditAction.UPDATE,
    changed_fields: list[str] | None = None,
    outcome: str | None = None,
) -> None:
    """Strictly audit a successful platform-admin override mutation on an event (ADR-052-R4).

    Records bounded identifiers and safe outcome metadata only. Request
    attribution comes from the HTTP boundary, and strict persistence lets the
    caller roll back a related database mutation if audit storage fails.
    """
    actor_type, actor_id = get_actor_from_request(request)
    new_state: dict[str, Any] = {
        "operation": operation,
        "authority_source": "platform_admin",
        "event_id": str(event.pk),
        "effective_actor_user_id": effective_actor_id,
    }
    if changed_fields:
        new_state["changed_fields"] = sorted(changed_fields)
    if outcome:
        new_state["outcome"] = outcome
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=_entity_id_from_uuid(event.pk),
            entity_ref=str(event.pk),
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            new_state=new_state,
            context="ctf_platform_admin_event_action",
            source_ip=get_client_ip(request),
            request_id=get_request_id(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
        ),
        strict=True,
    )


def _entity_id_from_uuid(entity_uuid: UUID) -> int:
    """Map a UUID to a positive int for AuditLog.entity_id."""
    return int.from_bytes(entity_uuid.bytes[:4], "big") % (2**31 - 1) or 1


def audit_public_registration_publication(*, actor_id: int, event_id: UUID, enabled: bool) -> None:
    """Strictly record an event's public-publication toggle without content or PII."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=_entity_id_from_uuid(event_id),
            entity_ref=str(event_id),
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            new_state={
                "ctf_public_registration_publication": "enabled" if enabled else "disabled",
                "event_id": str(event_id),
            },
            context="ctf_public_registration_publication",
        ),
        strict=True,
    )


def audit_public_registration_disposition(*, actor_id: int, event_id: UUID, request_id: UUID, disposition: str) -> None:
    """Strictly record a registration-request disposition using identifiers only."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=_entity_id_from_uuid(request_id),
            entity_ref=str(request_id),
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            new_state={
                "ctf_public_registration_disposition": disposition,
                "event_id": str(event_id),
                "request_id": str(request_id),
            },
            context="ctf_public_registration_disposition",
        ),
        strict=True,
    )


def audit_live_flag_repair(
    *,
    actor_id: int,
    challenge_id: UUID,
    flag_id: UUID,
    event_id: UUID,
    action: str,
) -> None:
    """Record a live flag repair without storing flag plaintext or hashes."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=_entity_id_from_uuid(challenge_id),
            entity_ref=str(challenge_id),
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            new_state={
                "ctf_live_flag_repair": action,
                "challenge_id": str(challenge_id),
                "flag_id": str(flag_id),
                "event_id": str(event_id),
            },
            context="ctf_live_flag_repair",
        )
    )


def audit_content_hydration(
    *,
    actor_id: int,
    event: CTFEvent,
    receipt: CTFContentHydrationReceipt,
    outcome: str,
) -> None:
    """Strictly record successful or idempotent native CTF content hydration."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=_entity_id_from_uuid(event.pk),
            entity_ref=str(event.pk),
            action=AuditAction.CREATE if outcome == "created" else AuditAction.UPDATE,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            new_state={
                "ctf_content_hydration": outcome,
                "event_id": str(event.pk),
                "scenario_id": receipt.scenario_id,
                "declared_digest": receipt.declared_digest,
                "challenge_count": receipt.challenge_count,
                "flag_count": receipt.flag_count,
                "hint_count": receipt.hint_count,
                "prerequisite_count": receipt.prerequisite_count,
            },
            context="ctf_content_hydration",
        ),
        strict=True,
    )


def audit_content_refresh(
    *,
    actor_id: int,
    event: CTFEvent,
    receipt: CTFContentHydrationReceipt,
    outcome: str,
    previous_digest: str,
    changed_categories: tuple[str, ...],
) -> None:
    """Strictly record an in-place managed-content refresh (issue #1971).

    Records the previous and target digests, bounded counts, and the categories
    of change (never content values, flag material, or object coordinates).
    """
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=_entity_id_from_uuid(event.pk),
            entity_ref=str(event.pk),
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            previous_state={"declared_digest": previous_digest},
            new_state={
                "ctf_content_refresh": outcome,
                "event_id": str(event.pk),
                "scenario_id": receipt.scenario_id,
                "declared_digest": receipt.declared_digest,
                "challenge_count": receipt.challenge_count,
                "flag_count": receipt.flag_count,
                "hint_count": receipt.hint_count,
                "prerequisite_count": receipt.prerequisite_count,
                "changed_categories": list(changed_categories),
            },
            context="ctf_content_refresh",
        ),
        strict=True,
    )


def audit_content_hydration_drift(
    *,
    actor_id: int | None,
    receipt: CTFContentHydrationReceipt,
) -> None:
    """Strictly record the first authorized mutation of hydrated content."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=_entity_id_from_uuid(receipt.event_id),
            entity_ref=str(receipt.event_id),
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.USER if actor_id else AuditActorType.SYSTEM,
            actor_id=actor_id,
            previous_state={"ctf_content_state": "pristine"},
            new_state={
                "ctf_content_state": "drifted",
                "event_id": str(receipt.event_id),
                "scenario_id": receipt.scenario_id,
                "reason": receipt.drift_reason,
            },
            context="ctf_content_hydration_drift",
        ),
        strict=True,
    )


def audit_event_page(
    *,
    actor_id: int,
    event_id: UUID,
    page_id: UUID,
    slug: str,
    body_length: int,
    action: str,
) -> None:
    """Record an organizer event-page mutation without storing the page body.

    Only identifiers, the slug, the source length, and the action are recorded;
    organizer-authored guidance content never enters the audit surface (#1854).
    """
    action_map = {
        "create": AuditAction.CREATE,
        "update": AuditAction.UPDATE,
        "delete": AuditAction.DELETE,
    }
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=_entity_id_from_uuid(event_id),
            entity_ref=str(event_id),
            action=action_map[action],
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            new_state={
                "ctf_event_page": action,
                "event_id": str(event_id),
                "page_id": str(page_id),
                "slug": slug,
                "body_length": body_length,
            },
            context="ctf_event_page",
        )
    )


def audit_range_recovery(
    *,
    actor_id: int | None,
    recovery: CTFRangeRecovery,
    participant: CTFParticipant,
    previous_status: str,
) -> None:
    """Record a completed participant range-recovery operation (#1018).

    Takes the ``CTFRangeRecovery`` record and the participant rather than
    their individual fields (keeps the parameter count within the project's
    limit): ``entity_id``, the strategy, and the replacement reference are
    all read off ``recovery``, and the resulting status is read off
    ``participant`` (already updated by :func:`ctf.services.range.recovery._ensure_participant_repointed`
    by the time this runs). ``entity_id`` is the old (pre-recovery)
    ``RangeInstance.pk`` -- already a positive int, so no UUID-to-int mapping
    is needed here (unlike :func:`audit_live_flag_repair`). Participant/event
    identity and the replacement reference are carried as sanitized strings
    in ``new_state``. The old range is always destroyed (no
    disposition/forensics concept).
    """
    old_range_instance_id = recovery.old_range_instance_id
    new_state: dict[str, Any] = {
        "status": participant.range_status,
        "event_id": str(recovery.event_id),
        "participant_id": str(participant.pk),
        "strategy": recovery.strategy,
        "replacement_range_instance_id": recovery.replacement_range_instance_id,
        "replacement_request_id": (str(recovery.replacement_request_id) if recovery.replacement_request_id else None),
    }
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=old_range_instance_id,
            action=AuditAction.RECOVER,
            actor_type=AuditActorType.USER if actor_id else AuditActorType.SYSTEM,
            actor_id=actor_id,
            previous_state={"status": previous_status, "range_instance_id": old_range_instance_id},
            new_state=new_state,
            context="ctf_range_recovery",
        )
    )


def audit_spare_provisioning(
    *,
    actor_id: int | None,
    event_id: UUID,
    target_count: int,
    existing: int,
    created: int,
) -> None:
    """Record one event spare-pool top-up action (#1018).

    One row per ``provision_event_spares`` call, not one per range -- each
    individual CMS range creation is already audited by
    ``cms.services.create_range`` (``AuditAction.PROVISION``).
    """
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=_entity_id_from_uuid(event_id),
            entity_ref=str(event_id),
            action=AuditAction.SPARE_PROVISION,
            actor_type=AuditActorType.USER if actor_id else AuditActorType.SYSTEM,
            actor_id=actor_id,
            new_state={
                "event_id": str(event_id),
                "target_count": target_count,
                "existing": existing,
                "created": created,
            },
            context="ctf_spare_provisioning",
        )
    )


def audit_vpn_profile_download(
    *,
    actor_id: int,
    participant_id: UUID,
    range_instance_id: int,
    generation: UUID,
    profile_version: str,
) -> None:
    """Record profile delivery without credential, topology, or provider data."""
    from shared.credential_delivery import audit_openvpn_profile_download

    audit_openvpn_profile_download(
        actor_id=actor_id,
        participant_id=participant_id,
        range_instance_id=range_instance_id,
        generation=generation,
        profile_version=profile_version,
        product="ctf",
    )


def audit_communication_release(
    *,
    actor_id: int | None,
    campaign_id: UUID,
    intent_id: UUID,
    workspace_id: int,
    recipient_count: int,
    channels: list[str],
) -> None:
    """Strictly record a scoped-communication intent release (ADR-051, #2048).

    Records only bounded identifiers, the workspace scope, the recipient count,
    and the selected channels. Never records subjects, bodies, recipient
    addresses, participant lists, provider payloads, or RAES documents. Strict:
    an audit failure rolls back the release transaction it runs inside.
    """
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.COMMUNICATION,
            entity_id=_entity_id_from_uuid(campaign_id),
            entity_ref=str(campaign_id),
            action=AuditAction.CREATE,
            actor_type=AuditActorType.USER if actor_id else AuditActorType.SYSTEM,
            actor_id=actor_id,
            new_state={
                "ctf_communication_release": "released",
                "campaign_id": str(campaign_id),
                "intent_id": str(intent_id),
                "workspace_id": workspace_id,
                "recipient_count": recipient_count,
                "channels": sorted(channels),
            },
            context="ctf_communication_release",
        ),
        strict=True,
    )


def audit_event_staff_change(
    *,
    actor_id: int,
    event_id: UUID,
    target_user_id: int,
    action: str,
    role: str | None = None,
    previous_role: str | None = None,
) -> None:
    """Strictly record an event-staff authority mutation (#1922).

    ``action`` is one of ``assigned`` / ``reroled`` / ``revoked``. Records only
    bounded IDs and role names — never email, tokens, or event content. Strict:
    audit failure rolls back the mutation it accompanies.
    """
    action_map = {
        "assigned": AuditAction.CREATE,
        "reroled": AuditAction.UPDATE,
        "revoked": AuditAction.DELETE,
    }
    new_state: dict[str, Any] = {
        "ctf_event_staff": action,
        "event_id": str(event_id),
        "target_user_id": target_user_id,
    }
    if role is not None:
        new_state["role"] = role
    if previous_role is not None:
        new_state["previous_role"] = previous_role
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=_entity_id_from_uuid(event_id),
            entity_ref=str(event_id),
            action=action_map.get(action, AuditAction.UPDATE),
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            new_state=new_state,
            context="ctf_event_staff",
        ),
        strict=True,
    )


def audit_event_ownership_transferred(
    *,
    actor_id: int,
    event_id: UUID,
    previous_owner_id: int,
    new_owner_id: int,
) -> None:
    """Strictly record a canonical-ownership transfer (#1922).

    Records only the event and old/new owner IDs. Strict: audit failure rolls
    back the transfer transaction.
    """
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=_entity_id_from_uuid(event_id),
            entity_ref=str(event_id),
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            previous_state={"owner_id": previous_owner_id},
            new_state={
                "ctf_event_ownership_transfer": "transferred",
                "event_id": str(event_id),
                "owner_id": new_owner_id,
            },
            context="ctf_event_ownership_transfer",
        ),
        strict=True,
    )
