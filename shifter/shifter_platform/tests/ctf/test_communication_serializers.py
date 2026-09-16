"""Bounded serializer projections for scoped communications (ADR-051, #2048, AC6).

The public projections must never leak another recipient, an email/delivery
coordinate, provider details, credentials, flags, or a raw RAES document. These
assert the EXACT set of exposed keys and that the recipient's address never
appears, so a future field addition that leaks PII fails the test.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.api.serializers.communication import (
    CommunicationCampaignSummarySerializer,
    CommunicationInboxItemSerializer,
)
from ctf.enums import ParticipantStatus
from ctf.models import CTFParticipant, RecipientSnapshot
from ctf.services.communication import CampaignDraft, create_campaign, release_campaign

pytestmark = pytest.mark.django_db


def _released(organizer_user, ctf_event):
    CTFParticipant.objects.create(
        event=ctf_event,
        email="recipient@secret.test",
        name="Recipient",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )
    campaign = create_campaign(
        organizer_user,
        str(workspace_services.resolve_personal_workspace(organizer_user).workspace_uuid),
        CampaignDraft(
            title="Kickoff",
            origin="organizer_staff",
            target_event_ids=[ctf_event.id],
            audience_spec={"kind": "event", "event_ids": [str(ctf_event.id)]},
            trigger_spec={"kind": "manual"},
            channels=["in_app"],
            subject="Welcome",
            body="Hello",
        ),
    )
    intent = release_campaign(campaign, occurrence_key="occ-ser", actor_user_id=organizer_user.id)
    return campaign, intent


def test_inbox_item_exposes_only_bounded_fields(organizer_user, ctf_event):
    _campaign, intent = _released(organizer_user, ctf_event)
    snapshot = RecipientSnapshot.objects.select_related("intent__revision", "receipt").get(intent=intent)

    data = CommunicationInboxItemSerializer(snapshot).data

    assert set(data) == {
        "message_id",
        "subject",
        "body",
        "content_profile",
        "origin",
        "acknowledgement_policy",
        "read_at",
        "acknowledged_at",
        "created_at",
    }
    # The recipient's address (and any other coordinate) must never surface.
    assert "recipient@secret.test" not in str(data)
    assert "delivery_coordinate" not in data
    assert "email" not in data


def test_campaign_summary_exposes_shape_not_recipients(organizer_user, ctf_event):
    campaign, _intent = _released(organizer_user, ctf_event)

    data = CommunicationCampaignSummarySerializer(campaign).data

    assert set(data) == {
        "id",
        "title",
        "status",
        "origin",
        "channels",
        "acknowledgement_policy",
        "target_event_count",
        "created_at",
    }
    assert data["target_event_count"] == 1
    assert "recipient@secret.test" not in str(data)
