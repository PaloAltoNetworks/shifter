"""Notification wave flows: scheduling fix, milestone emails, realtime bus (CTF-801..805)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from ctf.enums import NotificationStatus, NotificationType
from ctf.models import CTFNotification, CTFParticipant, CTFScheduledTask
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db


def _register(event, name, user=None):
    return CTFParticipant.objects.create(
        event=event,
        user=user,
        email=f"{name}@test.com",
        name=name,
        status="active",
        registered_at=timezone.now(),
    )


class TestScheduledAnnouncements:
    def test_legacy_schedule_is_retired(self, ctf_event_active, authenticated_organizer_client):
        response = call_json(
            authenticated_organizer_client,
            "post",
            "api_notification_list",
            kwargs={"event_id": ctf_event_active.pk},
            body={"subject": "Notice", "body": "Content"},
        )
        assert response.status_code == 410
        assert not CTFScheduledTask.objects.filter(task_type="send_notification").exists()


class TestParticipantAnnouncementFeed:
    def test_feed_lists_sent_only(self, ctf_event_active, participant_user):
        from management.services import set_active_ctf_event

        _register(ctf_event_active, "feed-reader", user=participant_user)
        set_active_ctf_event(participant_user, ctf_event_active.pk)
        CTFNotification.objects.create(
            event=ctf_event_active,
            created_by=ctf_event_active.created_by,
            notification_type="announcement",
            subject="Visible",
            body="sent body",
            status="sent",
        )
        CTFNotification.objects.create(
            event=ctf_event_active,
            notification_type=NotificationType.ANNOUNCEMENT.value,
            subject="Hidden draft",
            body="draft body",
            status=NotificationStatus.DRAFT.value,
            created_by=ctf_event_active.created_by,
        )

        client = Client()
        client.force_login(participant_user)
        resp = call_json(client, "get", "api_me_announcements")
        assert resp.status_code == 200
        subjects = [a["subject"] for a in resp.json()["announcements"]]
        assert subjects == ["Visible"]


class TestMilestoneEmails:
    def test_event_results_are_staged_without_delivery_claim(self, ctf_event_active):
        from ctf.models import CommunicationCampaign, CommunicationIntent
        from ctf.services.notification import send_event_results

        result = send_event_results(ctf_event_active.pk)
        assert result["outcome"] == "channel_unavailable"
        assert CommunicationCampaign.objects.get().channels == ["email"]
        assert not CommunicationIntent.objects.exists()
        assert not CTFNotification.objects.exists()

    def test_complete_event_triggers_results(self, ctf_event_active, monkeypatch):
        from ctf.services.event import complete_event

        calls = []
        monkeypatch.setattr("ctf.services.notification.send_event_results", lambda event_id: calls.append(event_id))
        ctf_event_active.event_end = timezone.now() - timedelta(minutes=1)
        ctf_event_active.save(update_fields=["event_end", "updated_at"])
        assert complete_event(ctf_event_active) is True
        assert calls == [ctf_event_active.pk]

    def test_range_ready_fires_once_per_transition(self, ctf_event_active, monkeypatch):
        from ctf.services.range.status import get_range_status

        participant = _register(ctf_event_active, "racer")
        participant.range_instance_id = 42
        participant.range_status = "provisioning"
        participant.save(update_fields=["range_instance_id", "range_status"])

        monkeypatch.setattr("ctf.bridges.cms_get_range_status", lambda _rid: "ready")
        monkeypatch.setattr("ctf.bridges.cms_has_openvpn_profile", lambda _u, _r: False)

        get_range_status(participant.pk)
        get_range_status(participant.pk)

        from ctf.models import CommunicationCampaign

        assert CommunicationCampaign.objects.filter(title="Your range is ready").count() == 1

    def test_participant_provision_failure_email(self, ctf_event_active):
        from ctf.services.notification import notify_participant_provision_failure

        participant = _register(ctf_event_active, "unlucky")
        assert notify_participant_provision_failure(participant.pk)["outcome"] == "channel_unavailable"
        assert not CTFNotification.objects.exists()


class TestRealtimeBus:
    def test_publish_creates_rows_when_enabled(self, ctf_event_active, participant_user, settings):
        from ctf.services.notification import publish_event_notification
        from shared.models import WebSocketNotification

        settings.WEBSOCKET_NOTIFICATIONS_ENABLED = True
        _register(ctf_event_active, "watcher", user=participant_user)

        publish_event_notification(ctf_event_active, "announcement", {"subject": "s", "body": "b"})

        rows = WebSocketNotification.objects.filter(topic=f"ctf:event:{ctf_event_active.pk}")
        recipient_ids = set(rows.values_list("recipient_id", flat=True))
        assert participant_user.pk in recipient_ids
        assert ctf_event_active.created_by_id in recipient_ids
        assert all(row.payload == {"kind": "refresh"} for row in rows)

    def test_publish_noops_when_disabled(self, ctf_event_active, settings):
        from ctf.services.notification import publish_event_notification
        from shared.models import WebSocketNotification

        settings.WEBSOCKET_NOTIFICATIONS_ENABLED = False
        publish_event_notification(ctf_event_active, "announcement", {"subject": "s"})
        assert not WebSocketNotification.objects.exists()

    def test_subscription_authorization(self, ctf_event_active, participant_user, organizer_user, django_user_model):
        from ctf.services.notification.realtime import _can_subscribe, event_topic

        _register(ctf_event_active, "member", user=participant_user)
        stranger = django_user_model.objects.create_user(username="s@test.com", email="s@test.com")
        topic = event_topic(ctf_event_active.pk)

        assert _can_subscribe(organizer_user, topic) is True
        assert _can_subscribe(participant_user, topic) is True
        assert _can_subscribe(stranger, topic) is False

    def test_first_blood_published_once(self, ctf_event_active, participant_user, monkeypatch):
        from ctf.enums import ChallengeCategory, ChallengeDifficulty
        from ctf.models import CTFChallenge
        from ctf.services import submit_flag

        challenge = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="FB",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_format="FLAG{...}",
        )
        solver_one = _register(ctf_event_active, "fb-one", user=participant_user)
        solver_two = _register(ctf_event_active, "fb-two")

        published = []
        monkeypatch.setattr(
            "ctf.services.notification.publish_event_notification",
            lambda event, kind, payload, **kw: published.append(kind),
        )
        monkeypatch.setattr("ctf.services.submission.verify_flag", lambda _c, _f, **_kwargs: True)

        submit_flag(solver_one.pk, challenge.pk, "FLAG{x}")
        submit_flag(solver_two.pk, challenge.pk, "FLAG{x}")

        assert published.count("first_blood") == 1
