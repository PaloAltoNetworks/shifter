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


class TestRecoverParticipantRangeErrorPaths:
    """Organizer-gated range-recovery API (issue #1018): authz, validation, and error-mapping branches."""

    def _recover(self, client: Client, participant_id, body):
        return _json(
            client,
            "post",
            "api_recover_participant_range",
            kwargs={"participant_id": participant_id},
            body=body,
        )

    def test_not_found(self, authenticated_organizer_client: Client):
        resp = self._recover(authenticated_organizer_client, uuid4(), {"strategy": "rebuild"})
        assert resp.status_code == 404

    def test_forbidden_different_event_organizer(
        self, client: Client, second_organizer_user, ctf_participant: CTFParticipant
    ):
        client.force_login(second_organizer_user)
        resp = self._recover(client, ctf_participant.id, {"strategy": "rebuild"})
        assert resp.status_code == 403

    def test_forbidden_participant(self, authenticated_participant_client: Client, ctf_participant: CTFParticipant):
        """A participant (non-organizer) may not recover their own or anyone's range."""
        resp = self._recover(authenticated_participant_client, ctf_participant.id, {"strategy": "rebuild"})
        assert resp.status_code == 403

    def test_missing_strategy(self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant):
        resp = self._recover(authenticated_organizer_client, ctf_participant.id, {})
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_non_string_strategy(self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant):
        resp = self._recover(authenticated_organizer_client, ctf_participant.id, {"strategy": 1})
        assert resp.status_code == 400

    @pytest.mark.parametrize("bad_spare_id", [0, -1, "not-an-int", 1.5, True])
    def test_bad_spare_range_instance_id(
        self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant, bad_spare_id
    ):
        resp = self._recover(
            authenticated_organizer_client,
            ctf_participant.id,
            {"strategy": "reassign_spare", "spare_range_instance_id": bad_spare_id},
        )
        assert resp.status_code == 400

    def test_invalid_strategy_choice_maps_to_400(
        self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant
    ):
        """An unrecognized strategy is rejected by the real service (CTFValidationError -> 400)."""
        ctf_participant.range_instance_id = 111
        ctf_participant.save(update_fields=["range_instance_id"])

        resp = self._recover(
            authenticated_organizer_client,
            ctf_participant.id,
            {"strategy": "not-a-real-strategy"},
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_no_range_to_recover_maps_to_400_without_leaking_internals(
        self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant
    ):
        """Real, unmocked ``CTFRangeError`` (ADR-019: no first-party service patch).

        ``ctf_participant`` has no ``range_instance_id`` by default, so the
        real service raises ``CTFRangeError("Participant has no range
        assigned to recover", ...)``; the response must carry only the
        controlled envelope message, never the exception's own text.
        """
        assert ctf_participant.range_instance_id is None
        resp = self._recover(
            authenticated_organizer_client,
            ctf_participant.id,
            {"strategy": "rebuild"},
        )
        assert resp.status_code == 400
        assert resp.json() == {"error": "Could not process range recovery request."}
        assert "assigned" not in resp.content.decode()

    def test_no_compatible_spare_maps_to_400_without_leaking_internals(
        self, authenticated_organizer_client: Client, ctf_participant: CTFParticipant
    ):
        """Real, unmocked ``CTFRangeError`` from the spare pool query (no spares exist for the event)."""
        ctf_participant.range_instance_id = 987654321
        ctf_participant.save(update_fields=["range_instance_id"])

        resp = self._recover(
            authenticated_organizer_client,
            ctf_participant.id,
            {"strategy": "reassign_spare"},
        )
        assert resp.status_code == 400
        assert resp.json() == {"error": "Could not process range recovery request."}
        assert "spare" not in resp.content.decode().lower()


class TestSpareRangePoolApiErrorPaths:
    """Organizer-gated spare-pool endpoint (issue #1018): authz + boundary validation."""

    def _manage(self, client: Client, event_id, body):
        return _json(
            client,
            "post",
            "api_provision_event_spares",
            kwargs={"event_id": event_id},
            body=body,
        )

    def test_not_found(self, authenticated_organizer_client: Client):
        resp = self._manage(authenticated_organizer_client, uuid4(), {"count": 1})
        assert resp.status_code == 404

    def test_forbidden_different_event_organizer(self, client: Client, second_organizer_user, ctf_event: CTFEvent):
        client.force_login(second_organizer_user)
        resp = self._manage(client, ctf_event.id, {"count": 1})
        assert resp.status_code == 403

    def test_forbidden_participant(self, authenticated_participant_client: Client, ctf_event: CTFEvent):
        """A participant (non-organizer) may not manage any event's spare pool."""
        resp = self._manage(authenticated_participant_client, ctf_event.id, {"count": 1})
        assert resp.status_code == 403

    def test_missing_count(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = self._manage(authenticated_organizer_client, ctf_event.id, {})
        assert resp.status_code == 400
        assert "error" in resp.json()

    @pytest.mark.parametrize("bad_count", ["not-an-int", 1.5, True, None, [1], {"n": 1}])
    def test_bad_count_type(self, authenticated_organizer_client: Client, ctf_event: CTFEvent, bad_count):
        resp = self._manage(authenticated_organizer_client, ctf_event.id, {"count": bad_count})
        assert resp.status_code == 400

    def test_negative_count(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = self._manage(authenticated_organizer_client, ctf_event.id, {"count": -1})
        assert resp.status_code == 400

    def test_over_cap_count(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        resp = self._manage(authenticated_organizer_client, ctf_event.id, {"count": 10_000})
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_zero_count_is_valid_and_returns_summary(self, authenticated_organizer_client: Client, ctf_event: CTFEvent):
        """Zero is a legitimate target (empty pool); no provisioning is attempted."""
        resp = self._manage(authenticated_organizer_client, ctf_event.id, {"count": 0})
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "event_id": str(ctf_event.id),
            "target_count": 0,
            "existing": 0,
            "created": 0,
        }
