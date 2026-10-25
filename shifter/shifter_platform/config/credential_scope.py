"""Compose domain-owned scalar ancestry without cross-domain model access."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.models import User

from cms.services import range_credential_scope
from ctf.services.credential_scope import event_credential_scope
from shared.authorization import TargetRef
from shared.identity_scope import ResourceScope
from workspaces.services import hierarchy_target_scope

if TYPE_CHECKING:
    from shared.credentials import CredentialContext


def temporary_participant_credential(user: object) -> CredentialContext:
    """Bind temporary proof to the exact CTF-owned live event lifecycle."""
    from ctf.services.participant.accounts import live_participant_for_user
    from shared.authorization import CredentialCeiling
    from shared.credentials import CredentialContext
    from shared.principal_port import principal_for_user

    if not isinstance(user, User):
        raise ValueError("Temporary credential unavailable")
    participant = live_participant_for_user(user)
    if participant is None:
        raise ValueError("Temporary credential unavailable")
    event_uuid = participant.event_id
    return CredentialContext(
        principal=principal_for_user(user),
        kind="temporary",
        credential_uuid=participant.pk,
        ceiling=CredentialCeiling(frozenset({"event.read", "event.participate"}), TargetRef("event", event_uuid)),
        scopes=frozenset(),
        event_uuid=event_uuid,
    )


def credential_target_scope(target: TargetRef) -> ResourceScope:
    """Resolve concrete target ancestry; never trust caller-supplied ancestry."""
    target_uuid = target.uuid
    if target_uuid is None:
        raise ValueError("Customer credential target requires an identity")
    if target.type == "event":
        return event_credential_scope(target_uuid)
    if target.type == "range":
        return range_credential_scope(target_uuid)
    return hierarchy_target_scope(target.type, target_uuid)
