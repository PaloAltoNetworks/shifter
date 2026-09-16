"""Campaign authoring service for scoped communications (ADR-051, #2048).

Creating a campaign is the confinement gate (AC1): the author proves active
membership of the campaign's single workspace, and EVERY target event must both
share that workspace and admit the author's notification capability. Content is
validated against the safe profile at authoring time; editing content creates a
new immutable revision (AC4). Authorization is additive -- workspace membership
never grants event or recipient authority, and a missing or unauthorized target
event returns the same opaque denial so identifiers cannot probe tenancy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction

import workspaces.services as workspace_services
from ctf.communication_contracts import (
    validate_acknowledgement_policy,
    validate_audience_spec,
    validate_channels,
    validate_message_content,
    validate_trigger_spec,
)
from ctf.enums import EventCapability
from ctf.enums_communication import CampaignStatus
from ctf.exceptions import CTFCommunicationError
from ctf.models import CommunicationCampaign, CommunicationTargetEvent, CTFEvent, MessageRevision
from ctf.services.event.staff import actor_has_event_capability

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CampaignDraft:
    """The organizer-supplied shape of a new campaign (ADR-051, #2048).

    A value object so campaign authoring is one bounded input, not a long
    positional/keyword list. The service validates every field before persisting.
    """

    title: str
    origin: str
    target_event_ids: list[UUID]
    audience_spec: dict[str, Any]
    trigger_spec: dict[str, Any]
    channels: list[str]
    subject: str
    body: str
    acknowledgement_policy: str = "none"
    actor_token_id: int | None = None


_TARGET_DENIED = CTFCommunicationError(
    "One or more target events are not available for this campaign",
    code="CTF_COMMUNICATION_TARGET_DENIED",
)


def _resolve_workspace(user: User, workspace_uuid: str | UUID) -> int:
    """Authorize active workspace membership for the communication operation."""
    try:
        authorization = workspace_services.authorize_workspace(
            user, workspace_uuid, workspace_services.WorkspaceOperation.USE_CTF_COMMUNICATIONS
        )
    except workspace_services.WorkspaceAuthorizationError as exc:
        raise CTFCommunicationError(
            "Workspace is not available for CTF communications",
            code="CTF_COMMUNICATION_WORKSPACE_DENIED",
        ) from exc
    return authorization.workspace_id


def _authorized_target_events(user: User, workspace_id: int, target_event_ids: list[UUID]) -> list[CTFEvent]:
    """Return the target events after confining them to the workspace and per-event capability.

    Every requested event must exist, carry the campaign's workspace scope, and
    admit the actor's ``notifications`` capability. Any failure raises one opaque
    denial (no partial success, no oracle).
    """
    if not target_event_ids:
        raise CTFCommunicationError("A campaign must target at least one event", code="CTF_COMMUNICATION_NO_TARGETS")
    unique_ids = list(dict.fromkeys(target_event_ids))
    events = {event.id: event for event in CTFEvent.objects.filter(id__in=unique_ids)}
    resolved: list[CTFEvent] = []
    for event_id in unique_ids:
        event = events.get(event_id)
        if event is None or event.workspace_id != workspace_id:
            raise _TARGET_DENIED
        if not actor_has_event_capability(user, event, EventCapability.NOTIFICATIONS.value):
            raise _TARGET_DENIED
        resolved.append(event)
    return resolved


def create_campaign(user: User, workspace_uuid: str | UUID, draft: CampaignDraft) -> CommunicationCampaign:
    """Create a draft campaign confined to one workspace with an initial revision."""
    workspace_id = _resolve_workspace(user, workspace_uuid)
    events = _authorized_target_events(user, workspace_id, draft.target_event_ids)

    audience = validate_audience_spec(draft.audience_spec)
    trigger = validate_trigger_spec(draft.trigger_spec)
    selected_channels = validate_channels(draft.channels)
    ack_policy = validate_acknowledgement_policy(draft.acknowledgement_policy)
    content = validate_message_content(
        {"subject": draft.subject, "body": draft.body},
        allowed_link_hosts=settings.CTF_COMMUNICATION_ALLOWED_LINK_HOSTS,
    )

    with transaction.atomic():
        campaign = CommunicationCampaign.objects.create(
            workspace_id=workspace_id,
            title=draft.title,
            origin=draft.origin,
            created_by=user,
            actor_token_id=draft.actor_token_id,
            status=CampaignStatus.DRAFT.value,
            audience_spec=audience,
            trigger_spec=trigger,
            channels=selected_channels,
            acknowledgement_policy=ack_policy,
        )
        CommunicationTargetEvent.objects.bulk_create(
            [CommunicationTargetEvent(campaign=campaign, event=event) for event in events]
        )
        MessageRevision.objects.create(
            campaign=campaign,
            revision_number=1,
            subject=content["subject"],
            body=content["body"],
            content_profile=content["profile"],
            content_digest=content["digest"],
        )
    logger.info("Created communication campaign %s in workspace %s", campaign.id, workspace_id)
    return campaign


def revise_message(campaign: CommunicationCampaign, *, subject: str, body: str) -> MessageRevision:
    """Create the next immutable message revision for a draft campaign.

    Editing content never mutates an existing revision (AC4); a new revision is
    appended. Only a draft campaign may be revised.
    """
    if campaign.status != CampaignStatus.DRAFT.value:
        raise CTFCommunicationError(
            "Only a draft campaign's message can be revised",
            code="CTF_COMMUNICATION_NOT_DRAFT",
        )
    content = validate_message_content(
        {"subject": subject, "body": body},
        allowed_link_hosts=settings.CTF_COMMUNICATION_ALLOWED_LINK_HOSTS,
    )
    with transaction.atomic():
        next_number = (
            MessageRevision.objects.filter(campaign=campaign)
            .order_by("-revision_number")
            .values_list("revision_number", flat=True)
            .first()
            or 0
        ) + 1
        return MessageRevision.objects.create(
            campaign=campaign,
            revision_number=next_number,
            subject=content["subject"],
            body=content["body"],
            content_profile=content["profile"],
            content_digest=content["digest"],
        )
