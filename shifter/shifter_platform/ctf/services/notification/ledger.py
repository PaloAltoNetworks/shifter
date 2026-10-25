"""Server-authored non-secret notices use the existing scoped ledger."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import transaction

import workspaces.services as ws
from ctf.exceptions import CTFCommunicationError
from ctf.models import CommunicationCampaign, CTFEvent, CTFParticipant
from ctf.services.communication import AdmissionActor, CampaignDraft, create_campaign, release_campaign
from ctf.services.communication.adapters import registered_channels


def stage_notice(
    event_id: UUID, *, kind: str, subject: str, body: str, occurrence: str, participant_id: UUID | None = None
) -> dict[str, str]:
    """One stable campaign per trusted occurrence; unavailable email is never dispatched.

    The original event owner remains the live author, with the same workspace and
    per-event checks as ordinary authoring. No missing actor becomes system trust.
    """
    with transaction.atomic():
        event = CTFEvent.objects.select_for_update().select_related("created_by").get(pk=event_id)
        identity = uuid5(NAMESPACE_URL, f"shifter:ctf-notice:{event.pk}:{kind}:{occurrence}:{participant_id or ''}")
        campaign = CommunicationCampaign.objects.filter(pk=identity).first()
        if campaign is None:
            try:
                binding = ws.authorize_bound_workspace(
                    event.created_by, event.workspace_id, ws.WorkspaceOperation.USE_CTF_COMMUNICATIONS
                )
            except ws.WorkspaceAuthorizationError:
                raise CTFCommunicationError("Unavailable", code="CTF_COMMUNICATION_WORKSPACE_DENIED") from None
            audience = (
                {"kind": "event", "event_ids": [str(event.pk)]}
                if participant_id is None
                else {"kind": "participant", "participant_ids": [str(participant_id)]}
            )
            campaign = create_campaign(
                event.created_by,
                binding.workspace_uuid,
                CampaignDraft(
                    title=subject,
                    origin="system_milestone",
                    target_event_ids=[event.pk],
                    audience_spec=audience,
                    trigger_spec={"kind": "manual"},
                    channels=["email"],
                    subject=subject,
                    body=body,
                ),
                campaign_id=identity,
            )
        if "email" not in registered_channels():
            return {"campaign_id": str(campaign.pk), "outcome": "channel_unavailable"}
        intent = release_campaign(
            campaign, occurrence_key="notice", admission=AdmissionActor(user_id=campaign.created_by_id)
        )
        return {"campaign_id": str(campaign.pk), "intent_id": str(intent.pk), "outcome": "accepted"}


def participant_notice(participant_id: UUID, *, kind: str, subject: str, body: str) -> dict[str, str]:
    """Bind a lifecycle notice to its participant and range occurrence."""

    participant = CTFParticipant.objects.select_related("event").get(pk=participant_id)
    # Range generations distinguish later genuine notices; retries use the same key.
    return stage_notice(
        participant.event_id,
        kind=kind,
        subject=subject,
        body=body,
        occurrence=str(participant.range_instance_id or "account"),
        participant_id=participant.pk,
    )
