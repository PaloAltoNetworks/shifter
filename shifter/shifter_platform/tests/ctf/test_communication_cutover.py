"""Legacy writer retirement and restart-safe staged ledger conversion (#2100)."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from ctf.exceptions import CTFCommunicationError
from ctf.models import CommunicationIntent, CTFNotification, CTFScheduledTask, ParticipantReceipt

pytestmark = pytest.mark.django_db


def legacy(owner, event, **kwargs):
    return CTFNotification.objects.create(
        event=event,
        created_by=owner,
        notification_type="announcement",
        subject="Welcome",
        body="Read the rules",
        **kwargs,
    )


def test_retired_writes_cannot_dispatch(organizer_user, ctf_event):
    row = legacy(organizer_user, ctf_event)
    client = APIClient()
    client.force_login(organizer_user)
    for route in (
        f"events/{ctf_event.pk}/notifications/",
        f"notifications/{row.pk}/send/",
        f"notifications/{row.pk}/cancel-schedule/",
        f"events/{ctf_event.pk}/invitations/send/",
        f"participants/{row.pk}/resend-invite/",
    ):
        response = client.post(f"/api/v1/ctf/{route}", {}, format="json")
        assert response.status_code == 410, response.content
        assert response.json()["error"]["code"] == "ctf_notification_retired"
    assert CTFNotification.objects.count() == 1
    assert not CommunicationIntent.objects.exists()


def test_service_sender_is_fenced(organizer_user, ctf_event):
    from ctf.services.notification import send_announcement

    with pytest.raises(CTFCommunicationError, match="RETIRED"):
        send_announcement(ctf_event.pk, "Hello", "Content", organizer_user)
    assert not CTFNotification.objects.exists()


def test_conversion_preserves_history_and_transfers_pending_ownership(organizer_user, ctf_event):
    from ctf.models import LegacyCommunication
    from ctf.services.communication.cutover import activate_cutover, migrate_legacy_batch, start_cutover

    historical = legacy(organizer_user, ctf_event, status="sent", sent_count=7)
    due = timezone.now() + timezone.timedelta(hours=2)
    pending = legacy(organizer_user, ctf_event, status="scheduled", scheduled_at=due)
    task = CTFScheduledTask.objects.create(
        event=ctf_event, task_type="send_notification", scheduled_for=due, metadata={"notification_id": str(pending.pk)}
    )
    start_cutover(legacy_producers_stopped=True)
    assert migrate_legacy_batch(batch_size=1) == 1
    assert migrate_legacy_batch(batch_size=1) == 1
    assert migrate_legacy_batch(batch_size=1) == 0
    activate_cutover()
    assert LegacyCommunication.objects.get(legacy_id=historical.pk).campaign_id is None
    mapping = LegacyCommunication.objects.get(legacy_id=pending.pk)
    assert mapping.disposition == "channel_unavailable"
    assert mapping.campaign.channels == ["email"]
    assert mapping.campaign.trigger_spec["due_at"] == due.isoformat()
    task.refresh_from_db()
    assert task.status == "cancelled"
    historical.refresh_from_db()
    assert historical.sent_count == 7
    assert not ParticipantReceipt.objects.exists()
    assert not CommunicationIntent.objects.exists()


@pytest.mark.parametrize("ambiguous", ["sending", "running"])
def test_ambiguous_inflight_work_blocks_fence(organizer_user, ctf_event, ambiguous):
    from ctf.services.communication.cutover import start_cutover

    row = legacy(organizer_user, ctf_event, status="sending" if ambiguous == "sending" else "scheduled")
    if ambiguous == "running":
        CTFScheduledTask.objects.create(
            event=ctf_event,
            task_type="send_notification",
            status="running",
            scheduled_for=timezone.now(),
            metadata={"notification_id": str(row.pk)},
        )
    with pytest.raises(CTFCommunicationError, match="CUTOVER"):
        start_cutover(legacy_producers_stopped=True)


def test_invalid_row_rolls_back_batch_and_prevents_activation(organizer_user, ctf_event):
    from ctf.models import LegacyCommunication
    from ctf.services.communication.cutover import activate_cutover, migrate_legacy_batch, start_cutover

    row = legacy(organizer_user, ctf_event)
    row.body = "<script>private-canary</script>"
    row.save()
    start_cutover(legacy_producers_stopped=True)
    with pytest.raises(CTFCommunicationError) as exc:
        migrate_legacy_batch()
    assert "private-canary" not in str(exc.value)
    assert not LegacyCommunication.objects.exists()
    with pytest.raises(CTFCommunicationError):
        activate_cutover()


def test_lifecycle_notice_stages_email_once_without_dispatch(organizer_user, ctf_event):
    from ctf.models import CommunicationCampaign
    from ctf.services.notification import send_event_results

    first = send_event_results(ctf_event.pk)
    second = send_event_results(ctf_event.pk)
    assert first == second
    assert first["outcome"] == "channel_unavailable"
    assert "sent" not in first
    assert CommunicationCampaign.objects.count() == 1
    assert CommunicationCampaign.objects.get().channels == ["email"]
    assert not CTFNotification.objects.exists()
    assert not CommunicationIntent.objects.exists()


def test_rollback_cannot_remove_an_initiated_fence():
    from importlib import import_module

    from django.apps import apps
    from django.db import connection
    from django.db.migrations.exceptions import IrreversibleError

    from ctf.services.communication.cutover import start_cutover

    start_cutover(legacy_producers_stopped=True)
    migration = import_module("ctf.migrations.0061_legacy_notification_fence")
    with pytest.raises(IrreversibleError):
        migration.remove_unused_fence(apps, connection.schema_editor())


def test_maintenance_batch_is_bounded_independently_of_interactive_rate(organizer_user, ctf_event, settings):
    from ctf.models import LegacyCommunication
    from ctf.services.communication.cutover import migrate_legacy_batch, start_cutover

    settings.CTF_COMMUNICATION_RATE_PER_ACTOR = 1
    legacy(organizer_user, ctf_event)
    legacy(organizer_user, ctf_event)
    start_cutover(legacy_producers_stopped=True)
    assert migrate_legacy_batch(batch_size=2) == 2
    assert LegacyCommunication.objects.count() == 2


def test_migrated_campaign_cannot_release_before_activation_or_email_readiness(organizer_user, ctf_event):
    from ctf.models import LegacyCommunication
    from ctf.services.communication import release_campaign
    from ctf.services.communication.cutover import activate_cutover, migrate_legacy_batch, start_cutover

    row = legacy(organizer_user, ctf_event)
    start_cutover(legacy_producers_stopped=True)
    migrate_legacy_batch()
    campaign = LegacyCommunication.objects.get(pk=row.pk).campaign
    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="bypass", actor_user_id=organizer_user.pk)
    activate_cutover()
    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="bypass", actor_user_id=organizer_user.pk)
    assert not CommunicationIntent.objects.exists()


@pytest.mark.parametrize("task_type", ["event_start", "event_end", "spin_up_ranges", "cleanup_ranges"])
def test_cutover_refuses_running_lifecycle_producers(ctf_event, task_type):
    from django.utils import timezone

    from ctf.exceptions import CTFCommunicationError
    from ctf.models import CTFScheduledTask
    from ctf.services.communication.cutover import start_cutover

    CTFScheduledTask.objects.create(
        event=ctf_event, task_type=task_type, scheduled_for=timezone.now(), status="running"
    )
    with pytest.raises(CTFCommunicationError):
        start_cutover(legacy_producers_stopped=True)
