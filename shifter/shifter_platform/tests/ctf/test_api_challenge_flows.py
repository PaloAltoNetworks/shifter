"""Organizer challenge, flag, hint, and file API flows.

Split from ``test_api_view_flows`` to keep test modules behavior-scoped
(see tests/test_test_suite_structure.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.urls import reverse

from ctf.models import CTFFlag, CTFHint
from tests.ctf._api_flow_helpers import call_json as _json
from tests.ctf.factories import create_challenge_data

if TYPE_CHECKING:
    from django.test import Client

    from ctf.models import CTFChallenge, CTFEvent

pytestmark = pytest.mark.django_db


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
        # Valid challenge data against a draft event must create (201).
        assert resp.status_code == 201

    def test_list_forbidden(self, client: Client, second_organizer_user, ctf_event: CTFEvent):
        client.force_login(second_organizer_user)
        resp = _json(client, "get", "api_challenge_list", kwargs={"event_id": ctf_event.id})
        assert resp.status_code == 403

    def test_detail_includes_rating_aggregate(
        self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge
    ):
        """CTF-120: organizers see the rating aggregate unless ratings are disabled."""
        resp = _json(
            authenticated_organizer_client, "get", "api_challenge_detail", kwargs={"challenge_id": ctf_challenge.id}
        )
        assert resp.status_code == 200
        assert resp.json()["rating"] == {"average": None, "count": 0}

        event = ctf_challenge.event
        event.rating_visibility = "disabled"
        event.save(update_fields=["rating_visibility"])
        resp = _json(
            authenticated_organizer_client, "get", "api_challenge_detail", kwargs={"challenge_id": ctf_challenge.id}
        )
        assert resp.status_code == 200
        assert resp.json()["rating"] is None

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
        # Valid challenge rename must succeed (200).
        assert resp.status_code == 200

    def test_detail_delete(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client, "delete", "api_challenge_detail", kwargs={"challenge_id": ctf_challenge.id}
        )
        # Deleting an existing challenge must succeed (204).
        assert resp.status_code == 204


class TestFlagHintFileApi:
    def test_add_flag(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_add_flag",
            kwargs={"challenge_id": ctf_challenge.id},
            body={"flag": "FLAG{added}", "flag_type": "static"},
        )
        # Valid flag payload must be created (201).
        assert resp.status_code == 201

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
        # Removing an existing flag must succeed (200).
        assert resp.status_code == 200

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
        # Valid hint payload must be created (201).
        assert resp.status_code == 201

    def test_hint_delete(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        hint = CTFHint.objects.create(challenge=ctf_challenge, text="h", penalty=5, order=0)
        resp = _json(authenticated_organizer_client, "post", "api_hint_delete", kwargs={"hint_id": hint.id})
        # Deleting an existing hint must succeed (204).
        assert resp.status_code == 204

    def test_hint_delete_not_found(self, authenticated_organizer_client: Client):
        resp = _json(authenticated_organizer_client, "post", "api_hint_delete", kwargs={"hint_id": uuid4()})
        # Unknown hint id: a client error is the correct outcome (400 bad id / 404
        # missing). This is an error-path test; success (2xx) would be the bug.
        assert resp.status_code in (400, 404)

    def test_files_get(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        resp = _json(
            authenticated_organizer_client, "get", "api_challenge_files", kwargs={"challenge_id": ctf_challenge.id}
        )
        assert resp.status_code == 200
        assert "files" in resp.json()

    def test_files_post_no_file(self, authenticated_organizer_client: Client, ctf_challenge: CTFChallenge):
        url = reverse("v1:ctf:api_challenge_files", kwargs={"challenge_id": ctf_challenge.id})
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
