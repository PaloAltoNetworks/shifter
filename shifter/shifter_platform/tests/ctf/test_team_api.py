"""Participant team lifecycle API flows (CTF-501..506)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from ctf.models import CTFParticipant, CTFTeam
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db


def _activate(user, event) -> None:
    from management.services import set_active_ctf_event

    set_active_ctf_event(user, event.pk)


def _register(event, user, name):
    """A registered, active participant bound to ``user``."""
    return CTFParticipant.objects.create(
        event=event,
        user=user,
        name=name,
        email=f"{name.lower().replace(' ', '-')}@test.com",
        status="active",
        registered_at=timezone.now(),
    )


@pytest.fixture
def team_event_participant(ctf_event_team, participant_user, authenticated_participant_client):
    _activate(participant_user, ctf_event_team)
    participant = _register(ctf_event_team, participant_user, "Team Captain")
    return ctf_event_team, participant, authenticated_participant_client


class TestTeamCreateJoinLeave:
    def test_create_makes_creator_captain(self, team_event_participant):
        _event, _participant, client = team_event_participant
        resp = call_json(client, "post", "api_team_create", body={"name": "Rocket Squad"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Rocket Squad"
        assert body["is_captain"] is True
        assert body["invite_code"]
        assert body["members"][0]["is_captain"] is True

    def test_create_rejects_duplicate_name(self, team_event_participant, django_user_model):
        event, _participant, client = team_event_participant
        call_json(client, "post", "api_team_create", body={"name": "Rocket Squad"})
        other_user = django_user_model.objects.create_user(username="second@test.com", email="second@test.com")
        other = _register(event, other_user, "Second Player")
        from ctf.exceptions import CTFValidationError
        from ctf.services.team import create_team

        with pytest.raises(CTFValidationError):
            create_team(other.pk, "Rocket Squad")

    def test_create_rejected_on_solo_event(self, ctf_event, participant_user, authenticated_participant_client):
        _activate(participant_user, ctf_event)
        _register(ctf_event, participant_user, "Solo Player")
        resp = call_json(authenticated_participant_client, "post", "api_team_create", body={"name": "Nope"})
        assert resp.status_code == 409

    def test_join_by_invite_code_and_capacity(self, team_event_participant, django_user_model):
        event, _captain, client = team_event_participant
        call_json(client, "post", "api_team_create", body={"name": "Joiners"})
        team = CTFTeam.objects.get(event=event, name="Joiners")
        event.team_size_limit = 2
        event.save(update_fields=["team_size_limit"])

        from ctf.exceptions import CTFStateError
        from ctf.services.team import join_team

        second_user = django_user_model.objects.create_user(username="joiner@test.com", email="joiner@test.com")
        second = _register(event, second_user, "Joiner")
        joined = join_team(second.pk, team.invite_code)
        assert joined.pk == team.pk

        third_user = django_user_model.objects.create_user(username="third@test.com", email="third@test.com")
        third = _register(event, third_user, "Third")
        with pytest.raises(CTFStateError):
            join_team(third.pk, team.invite_code)

    def test_join_api_rejects_bad_code(self, team_event_participant):
        _event, _participant, client = team_event_participant
        resp = call_json(client, "post", "api_team_join", body={"invite_code": "not-a-code"})
        assert resp.status_code == 404

    def test_leave_as_member_and_lone_captain_disbands(self, team_event_participant, django_user_model):
        event, captain, client = team_event_participant
        call_json(client, "post", "api_team_create", body={"name": "Leavers"})
        team = CTFTeam.objects.get(event=event, name="Leavers")

        from ctf.services.team import join_team, leave_team

        member_user = django_user_model.objects.create_user(username="leaver@test.com", email="leaver@test.com")
        member = _register(event, member_user, "Leaver")
        join_team(member.pk, team.invite_code)

        # Captain with teammates cannot leave.
        from ctf.exceptions import CTFStateError

        with pytest.raises(CTFStateError):
            leave_team(captain.pk)

        leave_team(member.pk)
        member.refresh_from_db()
        assert member.team_id is None

        resp = call_json(client, "post", "api_team_leave")
        assert resp.status_code == 200
        assert not CTFTeam.objects.filter(pk=team.pk).exists()


class TestCaptainActions:
    @pytest.fixture
    def team_with_member(self, team_event_participant, django_user_model):
        event, captain, client = team_event_participant
        call_json(client, "post", "api_team_create", body={"name": "Captains"})
        team = CTFTeam.objects.get(event=event, name="Captains")
        member_user = django_user_model.objects.create_user(username="mate@test.com", email="mate@test.com")
        member = _register(event, member_user, "Mate")
        from ctf.services.team import join_team

        join_team(member.pk, team.invite_code)
        return event, captain, member, team, client

    def test_rename(self, team_with_member):
        _event, _captain, _member, team, client = team_with_member
        resp = call_json(client, "post", "api_team_rename", body={"name": "Renamed Crew"})
        assert resp.status_code == 200
        team.refresh_from_db()
        assert team.name == "Renamed Crew"

    def test_regenerate_code(self, team_with_member):
        _event, _captain, _member, team, client = team_with_member
        old_code = team.invite_code
        resp = call_json(client, "post", "api_team_regenerate_code")
        assert resp.status_code == 200
        team.refresh_from_db()
        assert team.invite_code != old_code
        assert resp.json()["invite_code"] == team.invite_code

    def test_transfer_and_captain_only_guard(self, team_with_member):
        _event, _captain, member, team, client = team_with_member
        resp = call_json(client, "post", "api_team_transfer_captaincy", body={"participant_id": str(member.pk)})
        assert resp.status_code == 200
        team.refresh_from_db()
        assert team.captain_id == member.pk

        # The former captain can no longer run captain actions.
        resp = call_json(client, "post", "api_team_regenerate_code")
        assert resp.status_code == 403

    def test_remove_member(self, team_with_member):
        _event, _captain, member, _team, client = team_with_member
        resp = call_json(client, "post", "api_team_remove_member", body={"participant_id": str(member.pk)})
        assert resp.status_code == 200
        member.refresh_from_db()
        assert member.team_id is None

    def test_disband(self, team_with_member):
        _event, _captain, member, team, client = team_with_member
        resp = call_json(client, "post", "api_team_disband")
        assert resp.status_code == 200
        assert not CTFTeam.objects.filter(pk=team.pk).exists()
        member.refresh_from_db()
        assert member.team_id is None

    def test_invite_code_hidden_from_non_captain(self, team_with_member):
        _event, _captain, member, _team, _client = team_with_member
        from ctf.api import projections

        member.refresh_from_db()
        projection = projections.participant_team(member)
        assert projection["invite_code"] is None
        assert projection["is_captain"] is False


class TestTeamConfigGuards:
    def test_team_mode_frozen_after_start(self, ctf_event_active):
        """CTF-501: team settings are structural; frozen once the event starts."""
        from ctf.exceptions import CTFStateError
        from ctf.services.event import update_event

        with pytest.raises(CTFStateError):
            update_event(ctf_event_active.pk, {"team_mode": True})

    def test_unchanged_team_values_pass_after_start(self, ctf_event_active):
        from ctf.services.event import update_event

        updated = update_event(ctf_event_active.pk, {"team_mode": ctf_event_active.team_mode})
        assert updated.team_mode == ctf_event_active.team_mode

    def test_organizer_invite_assignment_honors_capacity(self, ctf_event_team, django_user_model):
        """CTF-505 (#648): assigning a team at invite time cannot exceed the cap."""
        from ctf.exceptions import CTFValidationError
        from ctf.services.participant import invite_participant
        from ctf.services.team import create_team, join_team

        ctf_event_team.team_size_limit = 2
        ctf_event_team.save(update_fields=["team_size_limit"])

        creator_user = django_user_model.objects.create_user(username="cap@test.com", email="cap@test.com")
        creator = _register(ctf_event_team, creator_user, "Cap")
        team = create_team(creator.pk, "Full House")

        mate_user = django_user_model.objects.create_user(username="mate2@test.com", email="mate2@test.com")
        mate = _register(ctf_event_team, mate_user, "Mate Two")
        join_team(mate.pk, team.invite_code)

        with pytest.raises(CTFValidationError):
            invite_participant(
                event_id=ctf_event_team.pk,
                email="overflow@test.com",
                name="Overflow",
                team_id=team.pk,
            )
