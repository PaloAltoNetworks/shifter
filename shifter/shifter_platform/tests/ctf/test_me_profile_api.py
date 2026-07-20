"""Participant self-profile and self-rename flows (CTF-610, #1593)."""

from __future__ import annotations

import pytest
from django.test import Client
from django.utils import timezone

from ctf.models import CTFParticipant
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db


@pytest.fixture
def me(ctf_event_active, participant_user, authenticated_participant_client):
    from management.services import set_active_ctf_event

    participant = CTFParticipant.objects.create(
        event=ctf_event_active,
        user=participant_user,
        email=participant_user.email,
        name="Self Player",
        affiliation="EMEA",
        status="active",
        registered_at=timezone.now(),
    )
    set_active_ctf_event(participant_user, ctf_event_active.pk)
    return participant, authenticated_participant_client


@pytest.fixture
def isolated_me(ctf_event_active, monkeypatch):
    """A participant on an isolated (#1206) account, logged in on a fresh client."""
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    from ctf.services.participant import create_participant_accounts
    from management.services import set_active_ctf_event

    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    set_active_ctf_event(participant.user, ctf_event_active.pk)
    profile = participant.user.profile
    profile.must_change_password = False
    profile.save(update_fields=["must_change_password"])
    fresh = Client()
    fresh.force_login(participant.user)
    return participant, fresh


class TestProfile:
    def test_get_profile(self, me):
        participant, client = me
        resp = call_json(client, "get", "api_me_profile")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Self Player"
        assert body["affiliation"] == "EMEA"
        assert body["role"] == "player"
        assert body["event"]["id"] == str(participant.event_id)
        assert body["username"] is None  # linked platform account, not isolated

    def test_patch_updates_name_and_affiliation(self, me):
        _participant, client = me
        resp = call_json(client, "patch", "api_me_profile", body={"name": "Rebrand", "affiliation": "APAC"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Rebrand"
        assert resp.json()["affiliation"] == "APAC"

    def test_patch_can_clear_affiliation_but_not_name(self, me):
        _participant, client = me
        cleared = call_json(client, "patch", "api_me_profile", body={"affiliation": ""})
        assert cleared.status_code == 200
        assert cleared.json()["affiliation"] == ""
        assert cleared.json()["name"] == "Self Player"
        # DRF rejects a blank name at the serializer; a whitespace name falls
        # through to the service validation.
        blank = call_json(client, "patch", "api_me_profile", body={"name": "   "})
        assert blank.status_code == 400


class TestSelfUsername:
    def test_change_own_username(self, isolated_me):
        participant, client = isolated_me
        resp = call_json(client, "post", "api_me_username", body={"username": "range-my-handle"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "range-my-handle"
        participant.user.refresh_from_db()
        assert participant.user.username == "range-my-handle"

    def test_change_rejects_invalid_and_duplicate(self, isolated_me, ctf_event_active, monkeypatch):
        monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
        from ctf.services.participant import create_participant_accounts

        other = create_participant_accounts(ctf_event_active.id, count=1)[0]
        _participant, client = isolated_me

        assert call_json(client, "post", "api_me_username", body={"username": "bad handle"}).status_code == 400
        taken = call_json(client, "post", "api_me_username", body={"username": other.user.username})
        assert taken.status_code == 400

    def test_plain_account_cannot_rename(self, me):
        _participant, client = me
        resp = call_json(client, "post", "api_me_username", body={"username": "range-nope"})
        assert resp.status_code == 400
