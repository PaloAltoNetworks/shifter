"""REST authorization and closed-envelope behavior for scoped communications."""

import pytest
from rest_framework.test import APIClient

from ctf.models import CommunicationCampaign, CommunicationIntent
from shared.api_tokens.models import ApiToken

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("personal_token_use_grant")]
URL = "/api/v1/ctf/communications/"


def test_scheduler_history_cannot_bypass_communication_scope_or_leak_errors(organizer_user, ctf_event):
    from django.utils import timezone

    from ctf.models import CTFScheduledTask

    task = CTFScheduledTask.objects.create(
        event=ctf_event,
        task_type="release_communication",
        scheduled_for=timezone.now(),
        error_message="private-error-canary",
        metadata={"intent_id": "missing"},
    )
    client, _ = token_client(organizer_user, ["ctf:event:read"])
    response = client.get(f"/api/v1/ctf/events/{ctf_event.pk}/tasks/")
    assert response.status_code == 200
    assert str(task.pk) not in response.content.decode()
    assert "private-error-canary" not in response.content.decode()


def body(event, owner):
    import workspaces.services as ws

    return {
        "workspace_id": str(ws.resolve_personal_workspace(owner).workspace_uuid),
        "title": "Welcome",
        "target_event_ids": [str(event.pk)],
        "audience_spec": {"kind": "event", "event_ids": [str(event.pk)]},
        "trigger_spec": {"kind": "manual"},
        "channels": ["in_app"],
        "subject": "Welcome",
        "body": "Read the rules",
    }


def token_client(owner, scopes):
    token, raw = ApiToken.create_token(name="test", created_by=owner, scopes=scopes)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client, token


def test_token_can_create_release_and_cancel(organizer_user, ctf_event):
    client, _ = token_client(organizer_user, ["ctf:communication:write", "ctf:communication:read"])
    response = client.post(URL, body(ctf_event, organizer_user), format="json")
    assert response.status_code == 201, response.content
    identity = response.json()["id"]
    assert client.get(URL, {"workspace_id": body(ctf_event, organizer_user)["workspace_id"]}).status_code == 200
    response = client.post(f"{URL}{identity}/release/", {"occurrence_key": "release-1"}, format="json")
    assert response.status_code == 202, response.content
    assert response.json()["status"] == "released"
    retry = client.post(f"{URL}{identity}/release/", {"occurrence_key": "release-1"}, format="json")
    assert retry.json()["id"] == response.json()["id"]
    assert CommunicationIntent.objects.count() == 1
    assert client.post(f"{URL}{identity}/cancel/", {}, format="json").status_code == 200


@pytest.mark.parametrize("scopes", [["ctf:event:write"], ["ctf:communication:read"]])
def test_wrong_write_scope_is_denied(organizer_user, ctf_event, scopes):
    client, _ = token_client(organizer_user, scopes)
    response = client.post(URL, body(ctf_event, organizer_user), format="json")
    assert response.status_code == 403
    assert not CommunicationCampaign.objects.exists()


def test_invalid_bearer_does_not_fall_back_to_session(organizer_user, ctf_event):
    client = APIClient()
    client.force_login(organizer_user)
    client.credentials(HTTP_AUTHORIZATION="Bearer shf_invalid.invalid")
    assert client.post(URL, body(ctf_event, organizer_user), format="json").status_code == 401


def test_unknown_fields_and_malformed_values_do_not_leak(organizer_user, ctf_event, caplog):
    client, _ = token_client(organizer_user, ["ctf:communication:write"])
    data = body(ctf_event, organizer_user)
    data["private-canary"] = "private-value"
    response = client.post(URL, data, format="json")
    assert response.status_code == 400
    assert "error" in response.json()
    assert "private-canary" not in response.content.decode() + caplog.text
    assert "private-value" not in response.content.decode() + caplog.text


def test_multi_event_campaign_is_not_disclosed_to_one_event_owner(organizer_user, second_organizer_user, ctf_event):
    import workspaces.services as ws
    from ctf.models import CTFEvent
    from ctf.services.communication import CampaignDraft, create_campaign

    second = CTFEvent.objects.create(
        name="Second",
        created_by=organizer_user,
        workspace_id=ctf_event.workspace_id,
        event_start=ctf_event.event_start,
        event_end=ctf_event.event_end,
    )
    campaign = create_campaign(
        organizer_user,
        ws.resolve_personal_workspace(organizer_user).workspace_uuid,
        CampaignDraft(
            title="private-campaign",
            origin="organizer_staff",
            target_event_ids=[ctf_event.pk, second.pk],
            audience_spec={"kind": "multi_event", "event_ids": [str(ctf_event.pk), str(second.pk)]},
            trigger_spec={"kind": "manual"},
            channels=["in_app"],
            subject="Secret",
            body="Secret",
        ),
    )
    CTFEvent.objects.filter(pk=second.pk).update(created_by=second_organizer_user)
    client, _ = token_client(organizer_user, ["ctf:communication:read"])
    assert client.get(f"{URL}{campaign.pk}/").status_code == 404
    response = client.get(URL, {"workspace_id": body(ctf_event, organizer_user)["workspace_id"]})
    assert response.status_code == 200
    assert "private-campaign" not in response.content.decode()
    visible = create_campaign(
        organizer_user,
        ws.resolve_personal_workspace(organizer_user).workspace_uuid,
        CampaignDraft(
            title="Visible",
            origin="organizer_staff",
            target_event_ids=[ctf_event.pk],
            audience_spec={"kind": "event", "event_ids": [str(ctf_event.pk)]},
            trigger_spec={"kind": "manual"},
            channels=["in_app"],
            subject="Visible",
            body="Visible",
        ),
    )
    for event_filter in ({}, {"event_id": str(ctf_event.pk)}):
        response = client.get(
            URL,
            {
                "workspace_id": body(ctf_event, organizer_user)["workspace_id"],
                "limit": 1,
                **event_filter,
            },
        )
        assert [item["id"] for item in response.json()["results"]] == [str(visible.pk)]
        assert response.json()["next_offset"] is None


def test_authoring_rate_limit_bounds_retained_drafts(organizer_user, ctf_event, settings):
    from django.core.cache import cache

    cache.clear()
    settings.CTF_COMMUNICATION_RATE_PER_ACTOR = 1
    client, _ = token_client(organizer_user, ["ctf:communication:write"])
    assert client.post(URL, body(ctf_event, organizer_user), format="json").status_code == 201
    response = client.post(URL, body(ctf_event, organizer_user), format="json")
    assert response.status_code == 429
    assert response["Retry-After"]
    assert CommunicationCampaign.objects.count() == 1


def test_unavailable_email_channel_is_not_accepted_for_delivery(organizer_user, ctf_event):
    client, _ = token_client(organizer_user, ["ctf:communication:write"])
    data = body(ctf_event, organizer_user)
    data["channels"] = ["email"]
    response = client.post(URL, data, format="json")
    assert response.status_code == 201
    response = client.post(f"{URL}{response.json()['id']}/release/", {"occurrence_key": "email-1"}, format="json")
    assert response.status_code == 503
    assert not CommunicationIntent.objects.exists()


def test_deleted_target_does_not_open_campaign_visibility(organizer_user, ctf_event):
    from django.utils import timezone

    from ctf.models import CTFEvent

    client, _ = token_client(organizer_user, ["ctf:communication:write", "ctf:communication:read"])
    response = client.post(URL, body(ctf_event, organizer_user), format="json")
    CTFEvent.all_objects.filter(pk=ctf_event.pk).update(deleted_at=timezone.now())
    assert client.get(f"{URL}{response.json()['id']}/").status_code == 404


@pytest.mark.parametrize("role", ["moderator", "judge", "co_organizer"])
def test_collection_authority_query_matches_live_staff_resolver(ctf_event, second_organizer_user, role):
    from django.utils import timezone

    from ctf.models import CTFEventStaff
    from ctf.services.authorization import events_with_capability, resolve_event_authority

    staff = CTFEventStaff.objects.create(event=ctf_event, user=second_organizer_user, role=role)

    def visible():
        return (
            events_with_capability(second_organizer_user, capability="notifications").filter(pk=ctf_event.pk).exists()
        )

    assert visible() == (
        resolve_event_authority(second_organizer_user, ctf_event, capability="notifications") is not None
    )
    CTFEventStaff.all_objects.filter(pk=staff.pk).update(deleted_at=timezone.now())
    assert not visible()
    assert resolve_event_authority(second_organizer_user, ctf_event, capability="notifications") is None
