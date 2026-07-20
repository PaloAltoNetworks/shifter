"""Cross-product credential-delivery rate and audit incumbents."""

from __future__ import annotations

from uuid import UUID

from django.core.cache import caches

from shared.audit import (
    AuditAction,
    AuditActorType,
    AuditEntityType,
    AuditEvent,
    audit_log,
)
from shared.rate_limit import consume_fixed_window


def credential_delivery_allowed(user_id: int, *, limit: int = 50, window: int = 3600) -> bool:
    """Consume the shared cross-worker credential-delivery budget."""
    cache = caches["launch_rate_limit"]
    count = consume_fixed_window(cache, f"credential-delivery:{user_id}", window)
    return count <= limit


def audit_openvpn_profile_download(
    *,
    actor_id: int,
    range_instance_id: int,
    generation: UUID,
    profile_version: str,
    product: str,
    participant_id: UUID | None = None,
) -> None:
    """Record profile delivery without credential, topology, or provider data."""
    state = {
        "product": product,
        "range_generation": str(generation),
        "channel": "openvpn",
        "profile_version": profile_version,
        "outcome": "delivered",
    }
    if participant_id is not None:
        state["participant_id"] = str(participant_id)
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CREDENTIAL,
            entity_id=range_instance_id,
            action=AuditAction.DOWNLOAD,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            new_state=state,
            context=f"{product}_vpn_profile_download",
        )
    )
