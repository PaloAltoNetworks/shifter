"""Organizer award API flows (CTF-204)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from tests.ctf._api_flow_helpers import call_json as _json

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


class TestParticipantAwardApi:
    def test_grant_list_and_revoke(self, authenticated_organizer_client: Client, ctf_participant):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_participant_awards",
            kwargs={"participant_id": ctf_participant.id},
            body={"points": 50, "reason": "Creative solve"},
        )
        assert resp.status_code == 201
        award_id = resp.json()["id"]
        assert resp.json()["points"] == 50

        ctf_participant.refresh_from_db()
        assert ctf_participant.cached_score == 50

        resp = _json(
            authenticated_organizer_client,
            "get",
            "api_participant_awards",
            kwargs={"participant_id": ctf_participant.id},
        )
        assert resp.status_code == 200
        assert resp.json()["awards"][0]["reason"] == "Creative solve"

        detail = _json(
            authenticated_organizer_client,
            "get",
            "api_participant_detail",
            kwargs={"participant_id": ctf_participant.id},
        )
        assert detail.status_code == 200
        assert detail.json()["awards"][0]["points"] == 50

        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_award_delete",
            kwargs={"award_id": award_id},
        )
        assert resp.status_code == 200
        ctf_participant.refresh_from_db()
        assert ctf_participant.cached_score == 0

    def test_negative_award_deducts(self, authenticated_organizer_client: Client, ctf_participant):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_participant_awards",
            kwargs={"participant_id": ctf_participant.id},
            body={"points": -25, "reason": "Rule violation"},
        )
        assert resp.status_code == 201
        ctf_participant.refresh_from_db()
        assert ctf_participant.cached_score == -25

    def test_revoke_unowned_award_is_not_found(self, authenticated_organizer_client: Client):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_award_delete",
            kwargs={"award_id": uuid4()},
        )
        assert resp.status_code == 404
