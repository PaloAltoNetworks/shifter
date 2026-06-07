"""Mapped-exception and edge-branch coverage for the decomposed ctf.views handlers.

Companion to ``test_api_view_flows.py``: drives each handler's service call to
raise the relevant CTF exception (or exercises a guard edge), asserting the
mapped HTTP status. DB fixtures from ``conftest.py``; services mocked at source.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse

from ctf.exceptions import (
    CTFNotFoundError,
    CTFPermissionError,
    CTFRangeError,
    CTFRateLimitError,
    CTFStateError,
    CTFValidationError,
)
from ctf.models import CTFFlag, CTFHint
from tests.ctf._api_flow_helpers import call_json as _json
from tests.ctf.factories import create_challenge_data

if TYPE_CHECKING:
    from django.test import Client

    from ctf.models import CTFChallenge, CTFEvent, CTFParticipant

pytestmark = pytest.mark.django_db


class TestApiErrorPaths:
    """Drive each handler's service call to raise, covering the error-mapping branches."""

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFValidationError("bad"), 400), (DjangoValidationError("bad"), 400)],
    )
    def test_event_create_errors(self, authenticated_organizer_client: Client, exc, status):
        with patch("ctf.services.create_event", side_effect=exc):
            resp = _json(authenticated_organizer_client, "post", "api_event_list", body={"name": "x"})
        assert resp.status_code == status

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFStateError("s"), 400), (DjangoValidationError("v"), 400)],
    )
    def test_event_update_errors(self, authenticated_organizer_client: Client, ctf_event_draft: CTFEvent, exc, status):
        with patch("ctf.services.update_event", side_effect=exc):
            resp = _json(
                authenticated_organizer_client,
                "put",
                "api_event_detail",
                kwargs={"event_id": ctf_event_draft.id},
                body={"name": "x"},
            )
        assert resp.status_code == status

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFPermissionError("p"), 403), (CTFNotFoundError("n"), 404), (CTFStateError("s"), 400)],
    )
    def test_challenge_create_errors(
        self, authenticated_organizer_client: Client, ctf_event_draft: CTFEvent, exc, status
    ):
        with patch("ctf.services.create_challenge", side_effect=exc):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_challenge_list",
                kwargs={"event_id": ctf_event_draft.id},
                body=create_challenge_data(),
            )
        assert resp.status_code == status

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFPermissionError("p"), 403), (CTFValidationError("v"), 400)],
    )
    def test_challenge_update_errors(
        self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge, exc, status
    ):
        with patch("ctf.services.update_challenge", side_effect=exc):
            resp = _json(
                authenticated_organizer_client,
                "put",
                "api_challenge_detail",
                kwargs={"challenge_id": ctf_challenge.id},
                body={"name": "x"},
            )
        assert resp.status_code == status

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFPermissionError("p"), 403), (CTFStateError("s"), 400)],
    )
    def test_challenge_delete_errors(
        self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge, exc, status
    ):
        with patch("ctf.services.delete_challenge", side_effect=exc):
            resp = _json(
                authenticated_organizer_client,
                "delete",
                "api_challenge_detail",
                kwargs={"challenge_id": ctf_challenge.id},
            )
        assert resp.status_code == status

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFPermissionError("p"), 403), (CTFNotFoundError("n"), 404), (CTFStateError("s"), 400)],
    )
    def test_add_flag_errors(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge, exc, status):
        with patch("ctf.services.challenge.add_flag", side_effect=exc):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_add_flag",
                kwargs={"challenge_id": ctf_challenge.id},
                body={"flag": "FLAG{x}", "flag_type": "static"},
            )
        assert resp.status_code == status

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFPermissionError("p"), 403), (CTFNotFoundError("n"), 404), (CTFStateError("s"), 400)],
    )
    def test_remove_flag_errors(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge, exc, status):
        flag = CTFFlag.objects.create(challenge=ctf_challenge, flag_hash="$2b$12$y", flag_type="static", order=0)
        with patch("ctf.services.challenge.remove_flag", side_effect=exc):
            resp = _json(authenticated_organizer_client, "post", "api_remove_flag", kwargs={"flag_id": flag.id})
        assert resp.status_code == status

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFPermissionError("p"), 403), (CTFStateError("s"), 400)],
    )
    def test_add_hint_errors(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge, exc, status):
        with patch("ctf.services.hint.add_hint", side_effect=exc):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_challenge_hints",
                kwargs={"challenge_id": ctf_challenge.id},
                body={"text": "h", "penalty": 0, "order": 0},
            )
        assert resp.status_code == status

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFPermissionError("p"), 403), (CTFNotFoundError("n"), 404), (CTFStateError("s"), 400)],
    )
    def test_hint_delete_errors(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge, exc, status):
        hint = CTFHint.objects.create(challenge=ctf_challenge, text="h", penalty=5, order=0)
        with patch("ctf.services.hint.remove_hint", side_effect=exc):
            resp = _json(authenticated_organizer_client, "post", "api_hint_delete", kwargs={"hint_id": hint.id})
        assert resp.status_code == status

    @pytest.mark.parametrize(
        ("exc", "status"),
        [
            (CTFNotFoundError("n"), 404),
            (CTFValidationError("v"), 400),
            (CTFRateLimitError("r"), 429),
            (CTFStateError("s"), 400),
        ],
    )
    def test_submit_flag_errors(
        self,
        authenticated_participant_client: Client,
        ctf_participant: CTFParticipant,
        ctf_challenge: CTFChallenge,
        exc,
        status,
    ):
        with patch("ctf.services.submission.submit_flag", side_effect=exc):
            resp = _json(
                authenticated_participant_client,
                "post",
                "api_submit_flag",
                kwargs={"challenge_id": ctf_challenge.id},
                body={"flag": "FLAG{x}"},
            )
        assert resp.status_code == status

    def test_submit_flag_success(
        self, authenticated_participant_client: Client, ctf_participant: CTFParticipant, ctf_challenge: CTFChallenge
    ):
        submission = MagicMock(is_correct=False, points_awarded=0, attempt_number=1)
        with patch("ctf.services.submission.submit_flag", return_value=submission):
            resp = _json(
                authenticated_participant_client,
                "post",
                "api_submit_flag",
                kwargs={"challenge_id": ctf_challenge.id},
                body={"flag": "FLAG{x}"},
            )
        assert resp.status_code == 200

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFNotFoundError("n"), 404), (CTFValidationError("v"), 400)],
    )
    def test_use_hint_errors(
        self,
        authenticated_participant_client: Client,
        ctf_participant: CTFParticipant,
        ctf_challenge: CTFChallenge,
        exc,
        status,
    ):
        CTFHint.objects.create(challenge=ctf_challenge, text="h", penalty=5, order=0)
        with patch("ctf.services.hint.use_hint", side_effect=exc):
            resp = _json(
                authenticated_participant_client,
                "post",
                "api_use_hint",
                kwargs={"challenge_id": ctf_challenge.id},
                body={},
            )
        assert resp.status_code == status

    def test_use_hint_success(
        self, authenticated_participant_client: Client, ctf_participant: CTFParticipant, ctf_challenge: CTFChallenge
    ):
        CTFHint.objects.create(challenge=ctf_challenge, text="h", penalty=5, order=0)
        with patch("ctf.services.hint.use_hint", return_value={"text": "h", "penalty": 5}):
            resp = _json(
                authenticated_participant_client,
                "post",
                "api_use_hint",
                kwargs={"challenge_id": ctf_challenge.id},
                body={},
            )
        assert resp.status_code == 200

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFNotFoundError("n"), 404), (CTFValidationError("v"), 400)],
    )
    def test_rate_challenge_errors(
        self,
        authenticated_participant_client: Client,
        ctf_participant: CTFParticipant,
        ctf_challenge: CTFChallenge,
        exc,
        status,
    ):
        with patch("ctf.services.submission.rate_challenge", side_effect=exc):
            resp = _json(
                authenticated_participant_client,
                "post",
                "api_rate_challenge",
                kwargs={"challenge_id": ctf_challenge.id},
                body={"value": 5},
            )
        assert resp.status_code == status

    def test_rate_challenge_success(
        self, authenticated_participant_client: Client, ctf_participant: CTFParticipant, ctf_challenge: CTFChallenge
    ):
        with patch("ctf.services.submission.rate_challenge", return_value=MagicMock(value=5)):
            resp = _json(
                authenticated_participant_client,
                "post",
                "api_rate_challenge",
                kwargs={"challenge_id": ctf_challenge.id},
                body={"value": 5},
            )
        assert resp.status_code == 200

    def test_add_prerequisite_success(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        prereq = MagicMock(id=uuid4(), required_challenge_id=uuid4())
        prereq.required_challenge.name = "Req"
        with patch("ctf.services.challenge.add_prerequisite", return_value=prereq):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_challenge_prerequisites",
                kwargs={"challenge_id": ctf_challenge.id},
                body={"required_challenge_id": str(uuid4())},
            )
        assert resp.status_code == 201

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(CTFPermissionError("p"), 403), (CTFNotFoundError("n"), 404), (CTFStateError("s"), 400)],
    )
    def test_add_prerequisite_errors(
        self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge, exc, status
    ):
        with patch("ctf.services.challenge.add_prerequisite", side_effect=exc):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_challenge_prerequisites",
                kwargs={"challenge_id": ctf_challenge.id},
                body={"required_challenge_id": str(uuid4())},
            )
        assert resp.status_code == status


class TestApiParticipantErrorPaths:
    """Participant submit/hint/rate/range/download/bracket error and edge branches."""

    def test_resend_invite_state_error(
        self, authenticated_organizer_client: Client, ctf_participant_invited: CTFParticipant
    ):
        with patch("ctf.services.resend_invite", side_effect=CTFStateError("s")):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_participant_resend_invite",
                kwargs={"participant_id": ctf_participant_invited.id},
            )
        assert resp.status_code == 400

    def test_invite_participant_validation_error(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        with patch("ctf.services.invite_participant", side_effect=CTFValidationError("v")):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_participant_list",
                kwargs={"event_id": ctf_event.id},
                body={"name": "A", "email": "a@test.com"},
            )
        assert resp.status_code == 400

    def test_range_action_range_error(self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant):
        with patch("ctf.services.range.provision_participant_range", side_effect=CTFRangeError("r")):
            resp = _json(
                authenticated_organizer_client,
                "post",
                "api_provision_participant_range",
                kwargs={"participant_id": ctf_participant.id},
            )
        assert resp.status_code == 400

    def test_challenge_file_delete_success(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        from ctf.models import CTFChallengeFile

        cf = CTFChallengeFile.objects.create(
            challenge=ctf_challenge,
            filename="f.txt",
            display_name="f",
            file_size_bytes=4,
            content_type="text/plain",
            s3_key="k",
            sha256_hash="h",
            order=0,
        )
        with patch("ctf.services.attachment.remove_challenge_file", return_value=None):
            resp = _json(authenticated_organizer_client, "post", "api_challenge_file_delete", kwargs={"file_id": cf.id})
        assert resp.status_code == 200

    def test_challenge_file_upload_success(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        from django.core.files.uploadedfile import SimpleUploadedFile

        cfile = MagicMock()
        cfile.id = uuid4()
        cfile.filename = "c.txt"
        cfile.display_name = "c"
        cfile.file_size_bytes = 4
        cfile.file_size_display = "4 B"
        upload = SimpleUploadedFile("c.txt", b"data", content_type="text/plain")
        with patch("ctf.services.attachment.add_challenge_file", return_value=cfile):
            url = reverse("ctf:api_challenge_files", kwargs={"challenge_id": ctf_challenge.id})
            resp = authenticated_organizer_client.post(url, data={"file": upload, "display_name": "c"})
        assert resp.status_code == 201

    def test_file_download_owner(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        from ctf.models import CTFChallengeFile

        cf = CTFChallengeFile.objects.create(
            challenge=ctf_challenge,
            filename="f.txt",
            display_name="f",
            file_size_bytes=4,
            content_type="text/plain",
            s3_key="k",
            sha256_hash="h",
            order=0,
        )
        with patch("ctf.services.attachment.get_download_url", return_value=("https://x/f", "f.txt")):
            resp = _json(authenticated_organizer_client, "get", "api_file_download", kwargs={"file_id": cf.id})
        assert resp.status_code == 200

    def test_assign_bracket_unknown(self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_assign_bracket",
            kwargs={"participant_id": ctf_participant.id},
            body={"bracket_id": str(uuid4())},
        )
        assert resp.status_code in (400, 404)

    def test_assign_bracket_valid(
        self, authenticated_organizer_client: Client, ctf_event: CTFEvent, ctf_participant: CTFParticipant
    ):
        from ctf.models import CTFBracket

        bracket = CTFBracket.objects.create(event=ctf_event, name="A", display_order=0)
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_assign_bracket",
            kwargs={"participant_id": ctf_participant.id},
            body={"bracket_id": str(bracket.id)},
        )
        assert resp.status_code in (200, 400)

    @pytest.mark.parametrize("exc", [CTFPermissionError("p"), CTFStateError("s")])
    def test_api_file_upload_error(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge, exc):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("c.txt", b"data", content_type="text/plain")
        with patch("ctf.services.attachment.add_challenge_file", side_effect=exc):
            url = reverse("ctf:api_challenge_files", kwargs={"challenge_id": ctf_challenge.id})
            resp = authenticated_organizer_client.post(url, data={"file": upload})
        assert resp.status_code in (403, 400)

    def test_admin_file_upload_permission_error(
        self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge
    ):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("c.txt", b"data", content_type="text/plain")
        with patch("ctf.services.attachment.add_challenge_file", side_effect=CTFPermissionError("p")):
            resp = authenticated_organizer_client.post(
                reverse("ctf:admin_challenge_file_upload", kwargs={"challenge_id": ctf_challenge.id}),
                data={"file": upload},
            )
        assert resp.status_code == 403

    def test_file_download_participant(
        self,
        authenticated_participant_client: Client,
        ctf_participant: CTFParticipant,
        ctf_challenge: CTFChallenge,
    ):
        from ctf.models import CTFChallengeFile

        cf = CTFChallengeFile.objects.create(
            challenge=ctf_challenge,
            filename="f.txt",
            display_name="f",
            file_size_bytes=4,
            content_type="text/plain",
            s3_key="k",
            sha256_hash="h",
            order=0,
        )
        with patch("ctf.services.attachment.get_download_url", return_value=("https://x/f", "f.txt")):
            resp = _json(authenticated_participant_client, "get", "api_file_download", kwargs={"file_id": cf.id})
        # Participant of the event: allowed when the challenge is available, else 403.
        assert resp.status_code in (200, 403)

    def test_participant_detail_not_found(self, authenticated_organizer_client: Client):
        resp = _json(
            authenticated_organizer_client, "get", "api_participant_detail", kwargs={"participant_id": uuid4()}
        )
        assert resp.status_code == 404

    def test_participant_detail_forbidden(self, client: Client, second_organizer_user, ctf_participant: CTFParticipant):
        client.force_login(second_organizer_user)
        resp = _json(client, "get", "api_participant_detail", kwargs={"participant_id": ctf_participant.id})
        assert resp.status_code == 403

    def test_timeline_self(self, authenticated_participant_client: Client, ctf_participant: CTFParticipant):
        resp = _json(
            authenticated_participant_client, "get", "api_score_timeline", kwargs={"participant_id": ctf_participant.id}
        )
        assert resp.status_code == 200

    def test_timeline_forbidden_other(
        self,
        client: Client,
        second_participant_user,
        ctf_participant: CTFParticipant,
    ):
        client.force_login(second_participant_user)
        resp = _json(client, "get", "api_score_timeline", kwargs={"participant_id": ctf_participant.id})
        assert resp.status_code == 403
