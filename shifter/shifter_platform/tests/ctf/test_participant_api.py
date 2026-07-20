"""Integration tests for the canonical participant CTF API (``/api/v1/ctf/me/*``).

These exercise the typed participant read surface end-to-end through the DRF
stack (permissions, event-scoped participant resolution, projections). They
assert both the happy-path shape and the participant-safety invariant: flag
hashes, flag formats, and solutions never appear in the participant projection.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from ctf.enums import ChallengeCategory, ChallengeDifficulty, ParticipantStatus
from ctf.models import CTFChallenge, CTFHint, CTFParticipant, CTFSubmission

from ._api_flow_helpers import call_json


def _activate(user, event) -> None:
    """Point the user's profile at ``event`` as their active CTF event."""
    from management.services import set_active_ctf_event

    set_active_ctf_event(user, event.pk)


class TestParticipantCurrentEvent:
    """``GET /api/v1/ctf/me/event/``."""

    def test_returns_current_event_and_self_state(
        self, authenticated_participant_client, ctf_participant, participant_user, ctf_event
    ):
        """A participant sees their event plus their own participant state."""
        _activate(participant_user, ctf_event)

        response = call_json(authenticated_participant_client, "get", "api_participant_current_event")

        assert response.status_code == 200
        body = response.json()
        assert body["event"]["id"] == str(ctf_event.id)
        assert body["event"]["name"] == ctf_event.name
        assert body["participant"]["id"] == str(ctf_participant.id)
        assert body["participant"]["cached_solve_count"] == 0

    def test_404_when_no_active_event(self, authenticated_participant_client, ctf_participant, participant_user):
        """A participant with no active event selected gets a 404 envelope."""
        response = call_json(authenticated_participant_client, "get", "api_participant_current_event")

        assert response.status_code == 404

    def test_forbidden_for_non_participant(self, authenticated_organizer_client):
        """An organizer (not a participant) is rejected."""
        response = call_json(authenticated_organizer_client, "get", "api_participant_current_event")

        assert response.status_code == 403


class TestParticipantChallengeList:
    """``GET /api/v1/ctf/me/challenges/``."""

    def test_lists_available_challenges_with_solve_state(
        self, authenticated_participant_client, ctf_participant, participant_user, ctf_event, ctf_challenge
    ):
        """The browse list carries solve state and never leaks flag/solution."""
        _activate(participant_user, ctf_event)
        CTFSubmission.objects.create(
            participant=ctf_participant,
            challenge=ctf_challenge,
            submitted_flag="FLAG{correct}",
            is_correct=True,
            points_awarded=ctf_challenge.points,
            attempt_number=1,
            ip_address="192.168.1.1",
        )

        response = call_json(authenticated_participant_client, "get", "api_participant_challenges")

        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        item = items[0]
        assert item["id"] == str(ctf_challenge.id)
        assert item["solved"] is True
        assert "flag_hash" not in item
        assert "flag_format" not in item
        assert "solution" not in item
        # CTF-113 / CTF-119: browse entries carry tag and topic labels for
        # client-side filtering.
        assert item["tags"] == []
        assert item["topics"] == []

    def test_list_includes_tag_and_topic_labels(
        self, authenticated_participant_client, ctf_participant, participant_user, ctf_event, ctf_challenge
    ):
        from ctf.services.challenge import update_challenge

        _activate(participant_user, ctf_event)
        update_challenge(
            ctf_challenge.pk,
            {"tags": ["XDR", "linux"], "topics": ["SQL Injection"]},
            actor_id=ctf_challenge.event.created_by_id,
        )

        response = call_json(authenticated_participant_client, "get", "api_participant_challenges")

        assert response.status_code == 200
        item = response.json()[0]
        assert sorted(item["tags"]) == ["linux", "xdr"]
        assert item["topics"] == ["sql injection"]

    def test_excludes_hidden_and_unreleased(
        self, authenticated_participant_client, ctf_participant, participant_user, ctf_event, ctf_challenge
    ):
        """Hidden and not-yet-released challenges are filtered server-side."""
        _activate(participant_user, ctf_event)
        CTFChallenge.objects.create(
            event=ctf_event,
            name="Hidden Challenge",
            description="secret",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$hidden_placeholder",
            visibility="hidden",
        )
        CTFChallenge.objects.create(
            event=ctf_event,
            name="Future Challenge",
            description="later",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$future_placeholder",
            release_time=timezone.now() + timedelta(days=1),
        )

        response = call_json(authenticated_participant_client, "get", "api_participant_challenges")

        assert response.status_code == 200
        names = {item["name"] for item in response.json()}
        assert names == {ctf_challenge.name}


class TestParticipantTeam:
    """``GET /api/v1/ctf/me/team/``."""

    def test_returns_team_and_members(
        self, authenticated_participant_client, ctf_participant_team, participant_user, ctf_event_team, ctf_team
    ):
        """A teamed participant sees their team and teammate names."""
        _activate(participant_user, ctf_event_team)
        CTFParticipant.objects.create(
            event=ctf_event_team,
            email="teammate@test.com",
            name="Teammate",
            team=ctf_team,
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )

        response = call_json(authenticated_participant_client, "get", "api_participant_team")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(ctf_team.id)
        member_names = {member["name"] for member in body["members"]}
        assert {"Team Participant", "Teammate"} <= member_names

    def test_404_when_solo(self, authenticated_participant_client, ctf_participant, participant_user, ctf_event):
        """A participant not on a team gets a 404 envelope."""
        _activate(participant_user, ctf_event)

        response = call_json(authenticated_participant_client, "get", "api_participant_team")

        assert response.status_code == 404


class TestParticipantChallengeDetail:
    """``GET /api/v1/ctf/me/challenges/<id>/``."""

    def _challenge_with_solution(self, event) -> CTFChallenge:
        return CTFChallenge.objects.create(
            event=event,
            name="Solve Me",
            description="detail body",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$detail_placeholder",
            flag_format="FLAG{...}",
            solution="the flag was in robots.txt",
        )

    def test_returns_detail_without_flag_or_solution_pre_end(
        self, authenticated_participant_client, ctf_participant, ctf_event
    ):
        """Detail carries hints/files but never the flag; solution stays hidden."""
        challenge = self._challenge_with_solution(ctf_event)
        CTFHint.objects.create(challenge=challenge, text="secret hint", penalty=10, order=0)

        response = call_json(
            authenticated_participant_client,
            "get",
            "api_participant_challenge_detail",
            kwargs={"challenge_id": challenge.id},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(challenge.id)
        assert "flag_hash" not in body
        assert "flag_format" not in body
        assert body["show_solution"] is False
        assert body["solution"] is None
        assert body["hints"][0]["unlocked"] is False
        assert body["hints"][0]["text"] is None

    def test_locked_challenge_is_readable_and_flagged_locked(
        self, authenticated_participant_client, ctf_participant, ctf_event
    ):
        """CTF-110: a LOCKED challenge stays readable and carries locked=True."""
        from ctf.enums import ChallengeVisibility

        challenge = self._challenge_with_solution(ctf_event)
        challenge.visibility = ChallengeVisibility.LOCKED.value
        challenge.save(update_fields=["visibility"])

        response = call_json(
            authenticated_participant_client,
            "get",
            "api_participant_challenge_detail",
            kwargs={"challenge_id": challenge.id},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["locked"] is True

    def test_visible_challenge_is_not_locked(self, authenticated_participant_client, ctf_participant, ctf_event):
        challenge = self._challenge_with_solution(ctf_event)

        response = call_json(
            authenticated_participant_client,
            "get",
            "api_participant_challenge_detail",
            kwargs={"challenge_id": challenge.id},
        )

        assert response.status_code == 200
        assert response.json()["locked"] is False

    def test_solution_revealed_after_event_ends(self, authenticated_participant_client, ctf_participant, ctf_event):
        """Once the event has ended the solution is surfaced for review."""
        challenge = self._challenge_with_solution(ctf_event)
        ctf_event.status = "ended"
        ctf_event.save(update_fields=["status"])

        response = call_json(
            authenticated_participant_client,
            "get",
            "api_participant_challenge_detail",
            kwargs={"challenge_id": challenge.id},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["show_solution"] is True
        assert body["solution"] == "the flag was in robots.txt"

    def test_404_for_unknown_challenge(self, authenticated_participant_client, ctf_participant):
        """An unknown challenge id returns a 404 envelope."""
        response = call_json(
            authenticated_participant_client,
            "get",
            "api_participant_challenge_detail",
            kwargs={"challenge_id": "00000000-0000-0000-0000-000000000000"},
        )

        assert response.status_code == 404

    def test_forbidden_for_challenge_in_other_event(
        self, authenticated_participant_client, ctf_participant, ctf_event_active
    ):
        """A challenge in an event the participant is not in is forbidden."""
        other = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Other Event Challenge",
            description="not yours",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$other_placeholder",
        )

        response = call_json(
            authenticated_participant_client,
            "get",
            "api_participant_challenge_detail",
            kwargs={"challenge_id": other.id},
        )

        assert response.status_code == 403
