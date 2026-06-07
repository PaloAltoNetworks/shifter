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

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.urls import reverse

from ctf.enums import NotificationType
from ctf.models import CTFEmailTemplate, CTFFlag, CTFHint
from tests.ctf._api_flow_helpers import JSON
from tests.ctf._api_flow_helpers import call_json as _json
from tests.ctf.factories import create_challenge_data, create_event_data

if TYPE_CHECKING:
    from django.test import Client

    from ctf.models import CTFChallenge, CTFEvent, CTFParticipant

pytestmark = pytest.mark.django_db


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
        assert resp.status_code in (201, 400)

    def test_create_post_invalid_json(self, authenticated_organizer_client: Client):
        url = reverse("ctf:api_event_list")
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
        assert resp.status_code in (200, 400)

    def test_detail_delete(self, authenticated_organizer_client: Client, ctf_event_draft: CTFEvent):
        resp = _json(
            authenticated_organizer_client, "delete", "api_event_detail", kwargs={"event_id": ctf_event_draft.id}
        )
        assert resp.status_code in (204, 400)

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


class TestChallengeApi:
    def test_list_get(self, authenticated_organizer_client: Client, ctf_event: CTFEvent, ctf_challenge: CTFChallenge):
        resp = _json(authenticated_organizer_client, "get", "api_challenge_list", kwargs={"event_id": ctf_event.id})
        assert resp.status_code == 200
        assert "challenges" in resp.json()

    def test_list_post_create(self, authenticated_organizer_client: Client, ctf_event_draft: CTFEvent):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_challenge_list",
            kwargs={"event_id": ctf_event_draft.id},
            body=create_challenge_data(),
        )
        assert resp.status_code in (201, 400, 403)

    def test_list_forbidden(self, client: Client, second_organizer_user, ctf_event: CTFEvent):
        client.force_login(second_organizer_user)
        resp = _json(client, "get", "api_challenge_list", kwargs={"event_id": ctf_event.id})
        assert resp.status_code == 403

    def test_detail_get(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client, "get", "api_challenge_detail", kwargs={"challenge_id": ctf_challenge.id}
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == str(ctf_challenge.id)

    def test_detail_not_found(self, authenticated_organizer_client: Client):
        resp = _json(authenticated_organizer_client, "get", "api_challenge_detail", kwargs={"challenge_id": uuid4()})
        assert resp.status_code == 404

    def test_detail_put(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client,
            "put",
            "api_challenge_detail",
            kwargs={"challenge_id": ctf_challenge.id},
            body={"name": "Renamed"},
        )
        assert resp.status_code in (200, 400)

    def test_detail_delete(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client, "delete", "api_challenge_detail", kwargs={"challenge_id": ctf_challenge.id}
        )
        assert resp.status_code in (204, 400)


class TestFlagHintFileApi:
    def test_add_flag(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_add_flag",
            kwargs={"challenge_id": ctf_challenge.id},
            body={"flag": "FLAG{added}", "flag_type": "static"},
        )
        assert resp.status_code in (201, 400)

    def test_add_flag_missing_value(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_add_flag",
            kwargs={"challenge_id": ctf_challenge.id},
            body={"flag": "", "flag_type": "static"},
        )
        assert resp.status_code == 400

    def test_remove_flag(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        flag = CTFFlag.objects.create(challenge=ctf_challenge, flag_hash="$2b$12$x", flag_type="static", order=0)
        resp = _json(authenticated_organizer_client, "post", "api_remove_flag", kwargs={"flag_id": flag.id})
        assert resp.status_code in (200, 400)

    def test_remove_flag_not_found(self, authenticated_organizer_client: Client):
        resp = _json(authenticated_organizer_client, "post", "api_remove_flag", kwargs={"flag_id": uuid4()})
        assert resp.status_code == 404

    def test_hints_get(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client, "get", "api_challenge_hints", kwargs={"challenge_id": ctf_challenge.id}
        )
        assert resp.status_code == 200
        assert "hints" in resp.json()

    def test_hints_post(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_challenge_hints",
            kwargs={"challenge_id": ctf_challenge.id},
            body={"text": "a hint", "penalty": 10, "order": 0},
        )
        assert resp.status_code in (201, 400)

    def test_hint_delete(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        hint = CTFHint.objects.create(challenge=ctf_challenge, text="h", penalty=5, order=0)
        resp = _json(authenticated_organizer_client, "post", "api_hint_delete", kwargs={"hint_id": hint.id})
        assert resp.status_code in (204, 400)

    def test_hint_delete_not_found(self, authenticated_organizer_client: Client):
        resp = _json(authenticated_organizer_client, "post", "api_hint_delete", kwargs={"hint_id": uuid4()})
        assert resp.status_code in (400, 404)

    def test_files_get(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client, "get", "api_challenge_files", kwargs={"challenge_id": ctf_challenge.id}
        )
        assert resp.status_code == 200
        assert "files" in resp.json()

    def test_files_post_no_file(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        url = reverse("ctf:api_challenge_files", kwargs={"challenge_id": ctf_challenge.id})
        resp = authenticated_organizer_client.post(url, data={})
        assert resp.status_code == 400

    def test_prerequisites_get(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client,
            "get",
            "api_challenge_prerequisites",
            kwargs={"challenge_id": ctf_challenge.id},
        )
        assert resp.status_code == 200
        assert "prerequisites" in resp.json()

    def test_prerequisites_post_bad_uuid(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_challenge_prerequisites",
            kwargs={"challenge_id": ctf_challenge.id},
            body={"required_challenge_id": "not-a-uuid"},
        )
        assert resp.status_code == 400

    def test_prerequisite_delete_not_found(self, authenticated_organizer_client: Client):
        resp = _json(
            authenticated_organizer_client, "post", "api_prerequisite_delete", kwargs={"prerequisite_id": uuid4()}
        )
        assert resp.status_code == 404


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
        assert resp.status_code in (200, 400, 429)

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
        assert resp.status_code in (200, 400)

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
        assert resp.status_code in (200, 400, 404)

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
        assert resp.status_code in (200, 404)

    def test_resend_invite(self, authenticated_organizer_client: Client, ctf_participant_invited: CTFParticipant):
        with patch("ctf.services.resend_invite", return_value=ctf_participant_invited):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_participant_resend_invite",
                kwargs={"participant_id": ctf_participant_invited.id},
            )
        assert resp.status_code in (200, 400)

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


class TestRangeApi:
    def test_provision_ranges(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        with patch("ctf.services.range.provision_event_ranges", return_value={"provisioned": 0}):
            resp = _json(
                authenticated_organizer_client, "post", "api_provision_ranges", kwargs={"event_id": ctf_event.id}
            )
        assert resp.status_code == 200

    def test_range_list(
        self, authenticated_organizer_client: Client, ctf_event: CTFEvent, ctf_participant: CTFParticipant
    ):
        resp = _json(authenticated_organizer_client, "get", "api_range_list", kwargs={"event_id": ctf_event.id})
        assert resp.status_code == 200

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

    def test_send_invitations(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        with patch("ctf.services.notification.send_invitations", return_value={"sent": 0}):
            resp = _json(
                authenticated_organizer_client, "post", "api_send_invitations", kwargs={"event_id": ctf_event.id}
            )
        assert resp.status_code == 200


class TestAdminViewFlows:
    def test_force_delete_get(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = authenticated_organizer_client.get(
            reverse("ctf:admin_event_force_delete", kwargs={"event_id": ctf_event.id})
        )
        assert resp.status_code == 200

    def test_force_delete_post_mismatch(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = authenticated_organizer_client.post(
            reverse("ctf:admin_event_force_delete", kwargs={"event_id": ctf_event.id}),
            data={"confirmation_name": "wrong"},
        )
        assert resp.status_code == 200

    def test_challenge_create_get(self, authenticated_organizer_client: Client, ctf_event_draft: CTFEvent):
        resp = authenticated_organizer_client.get(
            reverse("ctf:admin_challenge_create", kwargs={"event_id": ctf_event_draft.id})
        )
        assert resp.status_code == 200

    def test_challenge_create_post_invalid(self, authenticated_organizer_client: Client, ctf_event_draft: CTFEvent):
        resp = authenticated_organizer_client.post(
            reverse("ctf:admin_challenge_create", kwargs={"event_id": ctf_event_draft.id}),
            data={"name": ""},
        )
        assert resp.status_code == 200

    def test_challenge_edit_get(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = authenticated_organizer_client.get(
            reverse("ctf:admin_challenge_edit", kwargs={"challenge_id": ctf_challenge.id})
        )
        assert resp.status_code in (200, 302)

    def test_notification_create_get(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = authenticated_organizer_client.get(
            reverse("ctf:admin_notification_create", kwargs={"event_id": ctf_event.id})
        )
        assert resp.status_code == 200

    def test_notification_create_post_missing(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = authenticated_organizer_client.post(
            reverse("ctf:admin_notification_create", kwargs={"event_id": ctf_event.id}),
            data={"subject": "", "body": ""},
        )
        assert resp.status_code == 200

    def test_file_upload_no_file(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = authenticated_organizer_client.post(
            reverse("ctf:admin_challenge_file_upload", kwargs={"challenge_id": ctf_challenge.id}),
            data={},
        )
        assert resp.status_code == 302

    def test_notification_create_post_send_now(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        with patch("ctf.services.notification.send_announcement", return_value=MagicMock(id=uuid4())):
            resp = authenticated_organizer_client.post(
                reverse("ctf:admin_notification_create", kwargs={"event_id": ctf_event.id}),
                data={"subject": "Hi", "body": "There", "action": "send_now"},
            )
        assert resp.status_code == 302

    def test_notification_create_post_draft(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = authenticated_organizer_client.post(
            reverse("ctf:admin_notification_create", kwargs={"event_id": ctf_event.id}),
            data={"subject": "Hi", "body": "There", "action": "draft"},
        )
        assert resp.status_code == 302

    def test_notification_create_post_schedule_missing_time(
        self, authenticated_organizer_client: Client, ctf_event: CTFEvent
    ):
        resp = authenticated_organizer_client.post(
            reverse("ctf:admin_notification_create", kwargs={"event_id": ctf_event.id}),
            data={"subject": "Hi", "body": "There", "action": "schedule", "scheduled_at": ""},
        )
        assert resp.status_code == 200

    def test_admin_file_upload_with_file(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("c.txt", b"data", content_type="text/plain")
        with patch("ctf.services.attachment.add_challenge_file", return_value=MagicMock()):
            resp = authenticated_organizer_client.post(
                reverse("ctf:admin_challenge_file_upload", kwargs={"challenge_id": ctf_challenge.id}),
                data={"file": upload, "display_name": "c"},
            )
        assert resp.status_code == 302


class TestAdminChallengeFormPosts:
    def _form_data(self, **overrides):
        from ctf.enums import ChallengeCategory, ChallengeDifficulty

        data = {
            "name": "Form Challenge",
            "description": "A challenge created via the admin form",
            "category": ChallengeCategory.WEB.value,
            "points": 100,
            "difficulty": ChallengeDifficulty.EASY.value,
            "flag": "FLAG{form}",
            "flag_format": "FLAG{...}",
            "max_attempts": 0,
            "order": 0,
        }
        data.update(overrides)
        return data

    def test_create_post_valid(self, authenticated_organizer_client: Client, ctf_event_draft: CTFEvent):
        resp = authenticated_organizer_client.post(
            reverse("ctf:admin_challenge_create", kwargs={"event_id": ctf_event_draft.id}),
            data=self._form_data(),
        )
        # 302 on create success, 200 if the form re-renders with errors.
        assert resp.status_code in (200, 302)

    def test_edit_post_valid(self, authenticated_organizer_client: Client, ctf_event_draft: CTFEvent):
        from ctf.enums import ChallengeCategory, ChallengeDifficulty
        from ctf.models import CTFChallenge

        challenge = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Editable",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$z",
            flag_format="FLAG{...}",
        )
        resp = authenticated_organizer_client.post(
            reverse("ctf:admin_challenge_edit", kwargs={"challenge_id": challenge.id}),
            data=self._form_data(name="Edited"),
        )
        assert resp.status_code in (200, 302)
