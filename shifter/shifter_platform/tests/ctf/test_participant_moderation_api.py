"""Participant moderation flows: ban, disqualify, role, hidden, rename (CTF-604/605/606/609)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from ctf.models import CTFParticipant, CTFTeam
from ctf.services.scoring import recompute_team_score
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db


def _register(event, user, name, **extra):
    return CTFParticipant.objects.create(
        event=event,
        user=user,
        name=name,
        email=f"{name.lower().replace(' ', '-')}@test.com",
        status="active",
        registered_at=timezone.now(),
        **extra,
    )


@pytest.fixture
def ctf_challenge_active(ctf_event_active):
    from ctf.enums import ChallengeCategory, ChallengeDifficulty
    from ctf.models import CTFChallenge

    return CTFChallenge.objects.create(
        event=ctf_event_active,
        name="Live Challenge",
        description="Find the flag",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$test_hash_placeholder",
        flag_format="FLAG{...}",
    )


@pytest.fixture
def participant_client(participant_user):
    """A client independent of the organizer's (the shared ``client`` fixture
    would make the second ``force_login`` clobber the first)."""
    from django.test import Client

    fresh = Client()
    fresh.force_login(participant_user)
    return fresh


@pytest.fixture
def moderated(ctf_event_active, participant_user, authenticated_organizer_client):
    participant = _register(ctf_event_active, participant_user, "Target Player")
    return ctf_event_active, participant, authenticated_organizer_client


def _action(client, route, participant, body=None):
    return call_json(client, "post", route, kwargs={"participant_id": participant.id}, body=body)


class TestBanUnban:
    def test_ban_records_reason_and_blocks_access(self, moderated, participant_client):
        from management.services import set_active_ctf_event

        event, participant, organizer_client = moderated
        set_active_ctf_event(participant.user, event.pk)

        resp = _action(organizer_client, "api_participant_ban", participant, {"reason": "abusive conduct"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "banned"
        assert resp.json()["status_reason"] == "abusive conduct"

        # CTF-605: the banned participant loses the whole me-surface.
        me = call_json(participant_client, "get", "api_participant_current_event")
        assert me.status_code == 403

    def test_unban_restores_registered_status(self, moderated):
        _event, participant, organizer_client = moderated
        _action(organizer_client, "api_participant_ban", participant)
        resp = _action(organizer_client, "api_participant_unban", participant)
        assert resp.status_code == 200
        assert resp.json()["status"] == "registered"
        assert resp.json()["status_reason"] == ""

    def test_unban_requires_banned_state(self, moderated):
        _event, participant, organizer_client = moderated
        resp = _action(organizer_client, "api_participant_unban", participant)
        assert resp.status_code == 409

    def test_ban_preserves_submission_history(self, moderated, ctf_challenge_active):
        from ctf.models import CTFSubmission

        _event, participant, organizer_client = moderated
        CTFSubmission.objects.create(
            participant=participant,
            challenge=ctf_challenge_active,
            submitted_flag="x",
            is_correct=True,
            points_awarded=100,
        )
        _action(organizer_client, "api_participant_ban", participant)
        assert CTFSubmission.objects.filter(participant=participant).count() == 1


class TestDisqualifyRequalify:
    def test_disqualify_records_reason_and_keeps_view_access(self, moderated, participant_client):
        from management.services import set_active_ctf_event

        event, participant, organizer_client = moderated
        set_active_ctf_event(participant.user, event.pk)

        resp = _action(organizer_client, "api_participant_disqualify", participant, {"reason": "shared flags"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "disqualified"
        assert resp.json()["status_reason"] == "shared flags"

        # CTF-609: read access survives disqualification...
        me = call_json(participant_client, "get", "api_participant_current_event")
        assert me.status_code == 200
        assert me.json()["participant"]["status"] == "disqualified"

    def test_disqualified_participant_cannot_mutate_teams(
        self, ctf_event_team, participant_user, authenticated_organizer_client, participant_client
    ):
        from management.services import set_active_ctf_event

        participant = _register(ctf_event_team, participant_user, "Dq Team Actor")
        set_active_ctf_event(participant_user, ctf_event_team.pk)
        _action(authenticated_organizer_client, "api_participant_disqualify", participant)

        resp = call_json(participant_client, "post", "api_team_create", body={"name": "Ghost Team"})
        assert resp.status_code == 409

    def test_requalify_restores_standing(self, moderated):
        _event, participant, organizer_client = moderated
        _action(organizer_client, "api_participant_disqualify", participant)
        resp = _action(organizer_client, "api_participant_requalify", participant)
        assert resp.status_code == 200
        assert resp.json()["status"] == "registered"

    def test_requalify_requires_disqualified_state(self, moderated):
        _event, participant, organizer_client = moderated
        resp = _action(organizer_client, "api_participant_requalify", participant)
        assert resp.status_code == 409


class TestRoleAndHidden:
    def test_observer_role_blocks_competition_and_ranking(self, moderated, ctf_challenge_active):
        from ctf.exceptions import CTFPermissionError
        from ctf.services import submit_flag
        from ctf.services.scoring import get_scoreboard

        event, participant, organizer_client = moderated
        participant.cached_score = 50
        participant.save(update_fields=["cached_score"])
        resp = _action(organizer_client, "api_participant_role", participant, {"role": "observer"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "observer"

        with pytest.raises(CTFPermissionError):
            submit_flag(participant.id, ctf_challenge_active.id, "FLAG{nope}")
        assert all(row["participant_id"] != str(participant.id) for row in get_scoreboard(event.id))

    def test_observer_cannot_unlock_hints(self, moderated, ctf_challenge_active):
        from ctf.exceptions import CTFPermissionError
        from ctf.models import CTFHint
        from ctf.services import use_hint

        _event, participant, organizer_client = moderated
        hint = CTFHint.objects.create(challenge=ctf_challenge_active, text="try harder", penalty=5, order=1)
        _action(organizer_client, "api_participant_role", participant, {"role": "observer"})

        with pytest.raises(CTFPermissionError):
            use_hint(participant.id, hint.id)

    def test_invalid_role_rejected(self, moderated):
        _event, participant, organizer_client = moderated
        resp = _action(organizer_client, "api_participant_role", participant, {"role": "referee"})
        assert resp.status_code == 400

    def test_hidden_leaves_play_but_drops_rankings(self, moderated):
        from ctf.services.scoring import get_scoreboard

        event, participant, organizer_client = moderated
        participant.cached_score = 75
        participant.save(update_fields=["cached_score"])

        resp = _action(organizer_client, "api_participant_hidden", participant, {"hidden": True})
        assert resp.status_code == 200
        assert resp.json()["hidden"] is True
        assert all(row["participant_id"] != str(participant.id) for row in get_scoreboard(event.id))

        # Organizer roster still shows the row (CTF-606: admin view sees hidden).
        roster = call_json(organizer_client, "get", "api_participant_list", kwargs={"event_id": event.id})
        hidden_rows = [p for p in roster.json()["participants"] if p["id"] == str(participant.id)]
        assert hidden_rows and hidden_rows[0]["hidden"] is True

    def test_hidden_member_sheds_team_contribution(self, moderated):
        event, participant, organizer_client = moderated
        event.team_mode = True
        event.team_size_limit = 4
        event.save(update_fields=["team_mode", "team_size_limit", "updated_at"])
        team = CTFTeam.objects.create(event=event, name="Shade", invite_code="shade-1")
        participant.team = team
        participant.cached_score = 40
        participant.save(update_fields=["team", "cached_score"])
        recompute_team_score(team.id)

        _action(organizer_client, "api_participant_hidden", participant, {"hidden": True})
        team.refresh_from_db()
        assert team.cached_score == 0


class TestOrganizerRename:
    def test_rename_via_canonical_api(self, ctf_event_active, authenticated_organizer_client, monkeypatch):
        monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
        from ctf.services.participant import create_participant_accounts

        participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
        resp = _action(
            authenticated_organizer_client, "api_participant_username", participant, {"username": "range-blue-team"}
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "range-blue-team"

    def test_rename_rejects_invalid_handle(self, ctf_event_active, authenticated_organizer_client, monkeypatch):
        monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
        from ctf.services.participant import create_participant_accounts

        participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
        resp = _action(
            authenticated_organizer_client, "api_participant_username", participant, {"username": "no-prefix"}
        )
        assert resp.status_code == 400


class TestInviteEmailUniqueness:
    def test_invite_rejects_duplicate_email(self, ctf_event, authenticated_organizer_client, monkeypatch):
        monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
        first = call_json(
            authenticated_organizer_client,
            "post",
            "api_participant_list",
            kwargs={"event_id": ctf_event.id},
            body={"email": "dup@test.com", "name": "One"},
        )
        assert first.status_code == 201
        second = call_json(
            authenticated_organizer_client,
            "post",
            "api_participant_list",
            kwargs={"event_id": ctf_event.id},
            body={"email": "dup@test.com", "name": "Two"},
        )
        assert second.status_code == 400

    def test_bulk_import_partial_success(self, ctf_event, monkeypatch):
        monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
        from ctf.services import bulk_import_participants, invite_participant

        invite_participant(ctf_event.id, "taken@test.com", "Existing")
        result = bulk_import_participants(
            ctf_event.id,
            "Alice,alice@test.com\nBob,taken@test.com\nCara,alice@test.com\nbad-row\nDee,dee@test.com",
        )
        assert [p.name for p in result["created"]] == ["Alice", "Dee"]
        assert len(result["errors"]) == 3
