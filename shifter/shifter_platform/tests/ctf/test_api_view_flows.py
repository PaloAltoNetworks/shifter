"""Integration coverage for the CTF API/admin view flows.

These tests drive the decomposed views in ``ctf.views`` end-to-end through the
Django test client with real DB fixtures (see ``conftest.py``), exercising the
guard / dispatch / handler helpers that the SonarCloud S1142 refactor extracted.
Side-effecting services (range provisioning, notifications, force delete) are
mocked at source; CRUD paths use the test database.

Integration-style by design (one flow per test, shared fixtures) to avoid the
inline-mock OOM antipattern called out in CLAUDE.md.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.urls import reverse

from ctf.enums import NotificationType
from ctf.models import CTFEmailTemplate, CTFHint
from tests.ctf._api_flow_helpers import JSON
from tests.ctf._api_flow_helpers import call_json as _json
from tests.ctf.factories import create_event_data

if TYPE_CHECKING:
    from django.test import Client

    from ctf.models import CTFChallenge, CTFEvent, CTFParticipant

pytestmark = pytest.mark.django_db


@pytest.fixture
def recorded_email():
    """Record messages at the external SMTP boundary (ADR-019-R1).

    Replaces ``EmailMultiAlternatives`` with a recording double whose ``send()``
    signals ``delivered``, so a test can wait deterministically on the real
    ``shared.email.send_email_async`` background dispatch and then assert on what
    crossed the boundary. Mirrors the fixture in
    ``test_services/test_notification.py``: only the external SMTP boundary is
    patched, never a first-party ``ctf.services.*`` seam.
    """
    delivered = threading.Event()
    messages = []

    class RecordingMessage:
        def __init__(self, subject=None, body=None, from_email=None, to=None, **kwargs):
            self.subject = subject
            self.body = body
            self.from_email = from_email
            self.to = to
            messages.append(self)

        def attach_alternative(self, *args, **kwargs):
            pass

        def send(self):
            delivered.set()

    return RecordingMessage, delivered, messages


class TestEventApi:
    def test_list_get(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = _json(authenticated_organizer_client, "get", "api_event_list")
        assert resp.status_code == 200
        assert "events" in resp.json()

    def test_create_post_valid(self, authenticated_organizer_client: Client):
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        body = create_event_data()
        # The service parses ISO datetime strings; the model builders use objects.
        body["event_start"] = (now + timedelta(days=7)).isoformat()
        body["event_end"] = (now + timedelta(days=7, hours=8)).isoformat()
        resp = _json(authenticated_organizer_client, "post", "api_event_list", body=body)
        # Body is deliberately valid; the create must succeed (201), not silently 4xx.
        assert resp.status_code == 201

    def test_create_post_invalid_json(self, authenticated_organizer_client: Client):
        url = reverse("v1:ctf:api_event_list")
        resp = authenticated_organizer_client.post(url, data="not-json", content_type=JSON)
        assert resp.status_code == 400

    def test_detail_get(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = _json(authenticated_organizer_client, "get", "api_event_detail", kwargs={"event_id": ctf_event.id})
        assert resp.status_code == 200
        assert resp.json()["id"] == str(ctf_event.id)

    def test_detail_get_not_found(self, authenticated_organizer_client: Client):
        resp = _json(authenticated_organizer_client, "get", "api_event_detail", kwargs={"event_id": uuid4()})
        assert resp.status_code == 404

    def test_detail_get_forbidden(self, client: Client, second_organizer_user, ctf_event: CTFEvent):
        client.force_login(second_organizer_user)
        resp = _json(client, "get", "api_event_detail", kwargs={"event_id": ctf_event.id})
        assert resp.status_code == 403

    def test_detail_put(self, authenticated_organizer_client: Client, ctf_event_draft: CTFEvent):
        resp = _json(
            authenticated_organizer_client,
            "put",
            "api_event_detail",
            kwargs={"event_id": ctf_event_draft.id},
            body={"name": "Renamed Event"},
        )
        # Valid rename of a draft event must succeed (200).
        assert resp.status_code == 200

    def test_detail_delete(self, authenticated_organizer_client: Client, ctf_event_draft: CTFEvent):
        resp = _json(
            authenticated_organizer_client, "delete", "api_event_detail", kwargs={"event_id": ctf_event_draft.id}
        )
        # Deleting a draft event must succeed (204).
        assert resp.status_code == 204

    def test_force_delete_missing_confirmation(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = _json(
            authenticated_organizer_client, "post", "api_force_delete_event", kwargs={"event_id": ctf_event.id}, body={}
        )
        assert resp.status_code == 400

    def test_force_delete_ok(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        with patch(
            "ctf.services.force_delete_event",
            return_value={"event_name": ctf_event.name, "ranges_destroyed": 0},
        ):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_force_delete_event",
                kwargs={"event_id": ctf_event.id},
                body={"confirmation_name": ctf_event.name},
            )
        assert resp.status_code == 200

    def test_scenarios_get(self, authenticated_organizer_client: Client):
        with patch("ctf.bridges.cms_list_scenarios", return_value=[("basic", "Basic")]):
            resp = _json(authenticated_organizer_client, "get", "api_scenarios")
        assert resp.status_code == 200


class TestParticipantScopedApi:
    def test_submit_flag(
        self,
        authenticated_participant_client: Client,
        ctf_participant: CTFParticipant,
        ctf_challenge: CTFChallenge,
    ):
        resp = _json(
            authenticated_participant_client,
            "post",
            "api_submit_flag",
            kwargs={"challenge_id": ctf_challenge.id},
            body={"flag": "FLAG{guess}"},
        )
        # submit_flag enforces the same availability policy as hint unlock and
        # rating (ctf.services.challenge.assert_challenge_available_for_participant):
        # the ctf_event fixture is in REGISTRATION, not an active window, so the
        # precondition refuses the submission with 400 before verify_flag runs.
        # This pins the deterministic precondition outcome rather than accepting an
        # unreachable 200/429. Flag verification itself is exercised directly in
        # test_flag_source_of_truth.py and test_challenge_services.py.
        assert resp.status_code == 400

    def test_submit_flag_missing(
        self, authenticated_participant_client: Client, ctf_participant: CTFParticipant, ctf_challenge: CTFChallenge
    ):
        resp = _json(
            authenticated_participant_client,
            "post",
            "api_submit_flag",
            kwargs={"challenge_id": ctf_challenge.id},
            body={"flag": ""},
        )
        assert resp.status_code == 400

    def test_submit_flag_challenge_not_found(
        self, authenticated_participant_client: Client, ctf_participant: CTFParticipant
    ):
        resp = _json(
            authenticated_participant_client,
            "post",
            "api_submit_flag",
            kwargs={"challenge_id": uuid4()},
            body={"flag": "x"},
        )
        assert resp.status_code == 404

    def test_use_hint(
        self, authenticated_participant_client: Client, ctf_participant: CTFParticipant, ctf_challenge: CTFChallenge
    ):
        CTFHint.objects.create(challenge=ctf_challenge, text="h", penalty=5, order=0)
        resp = _json(
            authenticated_participant_client, "post", "api_use_hint", kwargs={"challenge_id": ctf_challenge.id}, body={}
        )
        # The hint exists, but use_hint enforces the same availability policy as
        # flag submission (ctf.services.challenge.assert_challenge_available_for_participant):
        # the ctf_event fixture is not in an active window, so the unlock is
        # deterministically refused with 400. This pins the precondition outcome
        # rather than accepting an unreachable 200.
        assert resp.status_code == 400

    def test_rate_challenge(
        self, authenticated_participant_client: Client, ctf_participant: CTFParticipant, ctf_challenge: CTFChallenge
    ):
        resp = _json(
            authenticated_participant_client,
            "post",
            "api_rate_challenge",
            kwargs={"challenge_id": ctf_challenge.id},
            body={"value": 5},
        )
        # value=5 is well-formed, but rate_challenge requires the participant to
        # have solved the challenge first (ctf.services.submission.rate_challenge);
        # the fixture participant has no solve, so the rating is deterministically
        # rejected with 400. This pins the precondition outcome, not an unreachable 200.
        assert resp.status_code == 400

    def test_rate_challenge_bad_value(
        self, authenticated_participant_client: Client, ctf_participant: CTFParticipant, ctf_challenge: CTFChallenge
    ):
        resp = _json(
            authenticated_participant_client,
            "post",
            "api_rate_challenge",
            kwargs={"challenge_id": ctf_challenge.id},
            body={"value": "five"},
        )
        assert resp.status_code == 400


class TestParticipantManagementApi:
    def test_list_get(
        self, authenticated_organizer_client: Client, ctf_event: CTFEvent, ctf_participant: CTFParticipant
    ):
        resp = _json(authenticated_organizer_client, "get", "api_participant_list", kwargs={"event_id": ctf_event.id})
        assert resp.status_code == 200
        assert "participants" in resp.json()

    def test_list_post_invite_missing_fields(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_participant_list",
            kwargs={"event_id": ctf_event.id},
            body={"name": "x"},
        )
        assert resp.status_code == 400

    def test_import_bad_shape(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_participant_import",
            kwargs={"event_id": ctf_event.id},
            body={"participants": "not-a-list"},
        )
        assert resp.status_code == 400

    def test_import_ok(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_participant_import",
            kwargs={"event_id": ctf_event.id},
            body={"participants": [{"name": "A", "email": "a@test.com"}, {"name": "", "email": ""}]},
        )
        assert resp.status_code == 200

    def test_detail_get(self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant):
        resp = _json(
            authenticated_organizer_client,
            "get",
            "api_participant_detail",
            kwargs={"participant_id": ctf_participant.id},
        )
        assert resp.status_code == 200

    def test_detail_delete(self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant):
        resp = _json(
            authenticated_organizer_client,
            "delete",
            "api_participant_detail",
            kwargs={"participant_id": ctf_participant.id},
        )
        # Deleting an existing participant must succeed (200).
        assert resp.status_code == 200

    def test_resend_invite(self, authenticated_organizer_client: Client, ctf_event: CTFEvent, recorded_email):
        """Resend runs the real credential-delivery service end-to-end; only the
        external SMTP boundary is mocked (ADR-019-R1). A participant with a real
        isolated account and a delivery email receives fresh login info, so the
        endpoint returns 200 and one message crosses the boundary.
        """
        from django.test import override_settings

        from ctf.services.participant import add_participant

        participant = add_participant(event_id=ctf_event.id, email="resend@test.com", name="Resend Target")
        message_cls, delivered, messages = recorded_email
        with (
            override_settings(CTF_FROM_EMAIL="ctf@test.com", SITE_URL="https://example.com"),
            patch("django.core.mail.EmailMultiAlternatives", message_cls),
        ):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_participant_resend_invite",
                kwargs={"participant_id": participant.id},
            )
            assert delivered.wait(timeout=2), "background send never ran"
        assert resp.status_code == 200
        assert messages[0].to == ["resend@test.com"]

    def test_assign_bracket_remove(self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_assign_bracket",
            kwargs={"participant_id": ctf_participant.id},
            body={"bracket_id": None},
        )
        assert resp.status_code == 200

    def test_assign_bracket_bad_uuid(self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_assign_bracket",
            kwargs={"participant_id": ctf_participant.id},
            body={"bracket_id": "not-a-uuid"},
        )
        assert resp.status_code == 400


class TestScoreboardApi:
    def test_scoreboard_get(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = _json(authenticated_organizer_client, "get", "api_scoreboard", kwargs={"event_id": ctf_event.id})
        assert resp.status_code == 200

    def test_scoreboard_not_found(self, authenticated_organizer_client: Client):
        resp = _json(authenticated_organizer_client, "get", "api_scoreboard", kwargs={"event_id": uuid4()})
        assert resp.status_code == 404

    def test_timeline_get(self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant):
        resp = _json(
            authenticated_organizer_client, "get", "api_score_timeline", kwargs={"participant_id": ctf_participant.id}
        )
        assert resp.status_code == 200


class TestNotificationApi:
    def test_list_get(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = _json(authenticated_organizer_client, "get", "api_notification_list", kwargs={"event_id": ctf_event.id})
        assert resp.status_code == 200
        assert "notifications" in resp.json()

    def test_list_post_announce(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        mock_notif = MagicMock(id=uuid4(), subject="S", status="sent", sent_count=0)
        with patch("ctf.services.notification.send_announcement", return_value=mock_notif):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_notification_list",
                kwargs={"event_id": ctf_event.id},
                body={"subject": "S", "body": "B"},
            )
        assert resp.status_code == 201

    def test_list_post_missing(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_notification_list",
            kwargs={"event_id": ctf_event.id},
            body={"subject": "", "body": ""},
        )
        assert resp.status_code == 400

    def test_send_not_found(self, authenticated_organizer_client: Client):
        resp = _json(
            authenticated_organizer_client, "post", "api_notification_send", kwargs={"notification_id": uuid4()}
        )
        assert resp.status_code == 404

    def test_email_template_get_default(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = _json(
            authenticated_organizer_client,
            "get",
            "api_event_email_template",
            kwargs={"event_id": ctf_event.id, "notification_type": NotificationType.INVITE.value},
        )
        assert resp.status_code == 404

    def test_email_template_bad_type(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = _json(
            authenticated_organizer_client,
            "get",
            "api_event_email_template",
            kwargs={"event_id": ctf_event.id, "notification_type": "bogus"},
        )
        assert resp.status_code == 400

    def test_email_template_put_then_delete(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        ntype = NotificationType.INVITE.value
        put = _json(
            authenticated_organizer_client,
            "put",
            "api_event_email_template",
            kwargs={"event_id": ctf_event.id, "notification_type": ntype},
            body={"subject": "S", "html_body": "<p>hi</p>", "text_body": "hi"},
        )
        assert put.status_code == 200
        assert CTFEmailTemplate.objects.filter(event=ctf_event, notification_type=ntype).exists()
        delete = _json(
            authenticated_organizer_client,
            "delete",
            "api_event_email_template",
            kwargs={"event_id": ctf_event.id, "notification_type": ntype},
        )
        assert delete.status_code == 200
        assert not CTFEmailTemplate.objects.filter(event=ctf_event, notification_type=ntype).exists()

    def test_email_template_put_rejects_template_tags(
        self, authenticated_organizer_client: Client, ctf_event: CTFEvent
    ):
        ntype = NotificationType.INVITE.value
        resp = _json(
            authenticated_organizer_client,
            "put",
            "api_event_email_template",
            kwargs={"event_id": ctf_event.id, "notification_type": ntype},
            body={
                "subject": "S",
                "html_body": "{% load i18n %}<p>{{ event_name }}</p>",
                "text_body": "{{ event_name }}",
            },
        )
        assert resp.status_code == 400
        assert not CTFEmailTemplate.objects.filter(event=ctf_event, notification_type=ntype).exists()

    def test_email_template_put_rejects_attribute_traversal(
        self, authenticated_organizer_client: Client, ctf_event: CTFEvent
    ):
        ntype = NotificationType.INVITE.value
        resp = _json(
            authenticated_organizer_client,
            "put",
            "api_event_email_template",
            kwargs={"event_id": ctf_event.id, "notification_type": ntype},
            body={
                "subject": "S",
                "html_body": "<p>{{ event.created_by.password }}</p>",
                "text_body": "hi",
            },
        )
        assert resp.status_code == 400
        assert not CTFEmailTemplate.objects.filter(event=ctf_event, notification_type=ntype).exists()

    def test_email_template_put_accepts_allowlisted_placeholders(
        self, authenticated_organizer_client: Client, ctf_event: CTFEvent
    ):
        ntype = NotificationType.INVITE.value
        resp = _json(
            authenticated_organizer_client,
            "put",
            "api_event_email_template",
            kwargs={"event_id": ctf_event.id, "notification_type": ntype},
            body={
                "subject": "S",
                "html_body": "<p>Hi {{ participant_name }}, join {{ event_name }}: {{ registration_url }}</p>",
                "text_body": "Hi {{ participant_name }}",
            },
        )
        assert resp.status_code == 200
        assert CTFEmailTemplate.objects.filter(event=ctf_event, notification_type=ntype).exists()


class TestRangeApi:
    def test_provision_ranges(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        """Provision-all enqueues a background spin-up task and returns 202 immediately."""
        from ctf.enums import ScheduledTaskStatus, ScheduledTaskType
        from ctf.models import CTFScheduledTask

        resp = _json(authenticated_organizer_client, "post", "api_provision_ranges", kwargs={"event_id": ctf_event.id})

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"
        # A real due-now spin-up task was created for the scheduler to run.
        task = CTFScheduledTask.objects.get(
            event=ctf_event,
            task_type=ScheduledTaskType.SPIN_UP_RANGES.value,
        )
        assert str(task.pk) == body["task_id"]
        assert task.status == ScheduledTaskStatus.PENDING.value

    def test_range_list(
        self, authenticated_organizer_client: Client, ctf_event: CTFEvent, ctf_participant: CTFParticipant
    ):
        resp = _json(authenticated_organizer_client, "get", "api_range_list", kwargs={"event_id": ctf_event.id})
        assert resp.status_code == 200
        body = resp.json()
        # Progress projection rides on the existing range-list endpoint.
        assert body["progress"]["counts"]["total"] == 1
        assert "task" in body["progress"]

    @pytest.mark.parametrize(
        ("route", "service_fn"),
        [
            ("api_provision_participant_range", "provision_participant_range"),
            ("api_destroy_participant_range", "destroy_participant_range"),
            ("api_stop_participant_range", "stop_participant_range"),
            ("api_start_participant_range", "start_participant_range"),
            ("api_restart_participant_range", "restart_participant_range"),
        ],
    )
    def test_participant_range_action(
        self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant, route, service_fn
    ):
        with patch(f"ctf.services.range.{service_fn}", return_value={"status": "ok"}):
            resp = _json(authenticated_organizer_client, "post", route, kwargs={"participant_id": ctf_participant.id})
        assert resp.status_code == 200

    def test_participant_range_action_not_found(self, authenticated_organizer_client: Client):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_provision_participant_range",
            kwargs={"participant_id": uuid4()},
        )
        assert resp.status_code == 404

    def test_send_invitations(self, authenticated_organizer_client: Client, ctf_event: CTFEvent, recorded_email):
        """Real ``send_login_info`` runs end-to-end; only the external SMTP
        boundary is mocked (ADR-019-R1). One participant with a delivery email
        means the endpoint sends one invitation and returns 200.
        """
        from django.test import override_settings

        from ctf.services.participant import add_participant

        add_participant(event_id=ctf_event.id, email="invitee@test.com", name="Invitee")
        message_cls, delivered, messages = recorded_email
        with (
            override_settings(CTF_FROM_EMAIL="ctf@test.com", SITE_URL="https://example.com"),
            patch("django.core.mail.EmailMultiAlternatives", message_cls),
        ):
            resp = _json(
                authenticated_organizer_client, "post", "api_send_invitations", kwargs={"event_id": ctf_event.id}
            )
            assert delivered.wait(timeout=2), "background send never ran"
        assert resp.status_code == 200
        assert resp.json()["sent"] == 1
        assert messages[0].to == ["invitee@test.com"]
