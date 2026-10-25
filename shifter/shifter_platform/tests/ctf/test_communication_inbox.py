"""Session-only, parent-scoped durable inbox and explicit receipt actions."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

import workspaces.services as ws
from ctf.models import CTFParticipant, ParticipantReceipt
from ctf.services.communication import CampaignDraft, create_campaign, release_campaign
from shared.api_tokens.models import ApiToken

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("personal_token_use_grant")]


@pytest.fixture
def inbox(organizer_user, ctf_event, django_user_model):
    user = django_user_model.objects.create_user(username="recipient")
    participant = CTFParticipant.objects.create(
        event=ctf_event,
        user=user,
        email="recipient@example.test",
        name="Recipient",
        status="active",
        registered_at=timezone.now(),
    )
    campaign = create_campaign(
        organizer_user,
        ws.resolve_personal_workspace(organizer_user).workspace_uuid,
        CampaignDraft(
            title="Notice",
            origin="organizer_staff",
            target_event_ids=[ctf_event.pk],
            audience_spec={"kind": "event", "event_ids": [str(ctf_event.pk)]},
            trigger_spec={"kind": "manual"},
            channels=["in_app"],
            subject="Notice",
            body="Read this",
            acknowledgement_policy="explicit",
        ),
    )
    intent = release_campaign(campaign, occurrence_key="inbox-1", actor_user_id=organizer_user.pk)
    snapshot = intent.recipient_snapshots.get()
    client = APIClient()
    client.force_login(user)
    url = f"/api/v1/ctf/me/events/{ctf_event.pk}/communications/"
    return client, user, participant, snapshot, url


def test_get_is_read_only_and_explicit_receipts_are_idempotent(inbox):
    client, _, _, snapshot, url = inbox
    response = client.get(url)
    assert response.status_code == 200, response.content
    assert response.json()["results"][0]["message_id"] == str(snapshot.pk)
    assert client.get(f"{url}{snapshot.pk}/").status_code == 200
    receipt = ParticipantReceipt.objects.get(snapshot=snapshot)
    assert receipt.read_at is None and receipt.acknowledged_at is None
    for action, field in [("read", "read_at"), ("acknowledge", "acknowledged_at")]:
        response = client.post(f"{url}{snapshot.pk}/{action}/", {}, format="json")
        assert response.status_code == 200, response.content
        receipt.refresh_from_db()
        first = getattr(receipt, field)
        assert first is not None
        assert client.post(f"{url}{snapshot.pk}/{action}/", {}, format="json").status_code == 200
        receipt.refresh_from_db()
        assert getattr(receipt, field) == first


def test_token_is_never_a_receipt_session(inbox):
    client, user, _, snapshot, url = inbox
    _, raw = ApiToken.create_token(
        name="read", created_by=user, scopes=["ctf:communication:read", "ctf:communication:write"]
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert client.get(url).status_code == 403
    assert client.post(f"{url}{snapshot.pk}/read/", {}, format="json").status_code == 403


def test_removed_or_other_parent_cannot_read_or_ack(inbox, django_user_model):
    from uuid import uuid4

    client, _, participant, snapshot, url = inbox
    assert client.get(f"/api/v1/ctf/me/events/{uuid4()}/communications/{snapshot.pk}/").status_code == 404
    participant.status = "banned"
    participant.save()
    assert client.get(url).status_code == 404
    assert client.post(f"{url}{snapshot.pk}/acknowledge/", {}, format="json").status_code == 404


def test_receipt_write_requires_csrf(inbox):
    _, user, _, snapshot, url = inbox
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    assert client.post(f"{url}{snapshot.pk}/read/", {}, format="json").status_code == 403
