"""Delegated event-staff roles: assignment and capability boundaries (CTF-607)."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from shared.auth import CTF_ORGANIZER_GROUP
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db


def _organizer(email: str) -> User:
    from management.services import get_user_profile

    user = User.objects.create_user(username=email, email=email, password="testpass123")  # nosec B106
    group, _ = Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)
    user.groups.add(group)
    profile = get_user_profile(user)
    profile.user_type = "ctf_organizer"
    profile.save(update_fields=["user_type"])
    return user


@pytest.fixture
def helper_organizer():
    return _organizer("helper@test.com")


@pytest.fixture
def helper_client(helper_organizer):
    fresh = Client()
    fresh.force_login(helper_organizer)
    return fresh


def _assign(client, event, email, role):
    return call_json(
        client, "post", "api_event_staff", kwargs={"event_id": event.id}, body={"email": email, "role": role}
    )


class TestStaffAssignment:
    def test_assign_list_and_revoke(self, ctf_event, authenticated_organizer_client, helper_organizer):
        resp = _assign(authenticated_organizer_client, ctf_event, "helper@test.com", "moderator")
        assert resp.status_code == 201
        assert resp.json()["role"] == "moderator"

        listing = call_json(authenticated_organizer_client, "get", "api_event_staff", kwargs={"event_id": ctf_event.id})
        assert [s["email"] for s in listing.json()["staff"]] == ["helper@test.com"]

        gone = call_json(
            authenticated_organizer_client,
            "delete",
            "api_event_staff_member",
            kwargs={"event_id": ctf_event.id, "user_id": helper_organizer.pk},
        )
        assert gone.status_code == 200
        listing = call_json(authenticated_organizer_client, "get", "api_event_staff", kwargs={"event_id": ctf_event.id})
        assert listing.json()["staff"] == []

    def test_reassign_changes_role(self, ctf_event, authenticated_organizer_client, helper_organizer):
        _assign(authenticated_organizer_client, ctf_event, "helper@test.com", "moderator")
        resp = _assign(authenticated_organizer_client, ctf_event, "helper@test.com", "judge")
        assert resp.status_code == 201
        listing = call_json(authenticated_organizer_client, "get", "api_event_staff", kwargs={"event_id": ctf_event.id})
        assert [s["role"] for s in listing.json()["staff"]] == ["judge"]

    def test_assign_rejects_unknown_email_and_bad_role(self, ctf_event, authenticated_organizer_client):
        assert _assign(authenticated_organizer_client, ctf_event, "nobody@test.com", "moderator").status_code == 404
        assert _assign(authenticated_organizer_client, ctf_event, "organizer@test.com", "sheriff").status_code == 400

    def test_assign_rejects_owner_and_non_organizer(self, ctf_event, authenticated_organizer_client, participant_user):
        assert _assign(authenticated_organizer_client, ctf_event, "organizer@test.com", "judge").status_code == 400
        assert _assign(authenticated_organizer_client, ctf_event, participant_user.email, "judge").status_code == 400


class TestModeratorCapabilities:
    @pytest.fixture
    def moderator_client(self, ctf_event, authenticated_organizer_client, helper_client):
        _assign(authenticated_organizer_client, ctf_event, "helper@test.com", "moderator")
        return helper_client

    def test_moderator_manages_participants(self, ctf_event, moderator_client, monkeypatch):
        monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
        listing = call_json(moderator_client, "get", "api_participant_list", kwargs={"event_id": ctf_event.id})
        assert listing.status_code == 200
        invited = call_json(
            moderator_client,
            "post",
            "api_participant_list",
            kwargs={"event_id": ctf_event.id},
            body={"email": "new@test.com", "name": "Newbie"},
        )
        assert invited.status_code == 201

    def test_moderator_cannot_touch_challenges_or_staff(self, ctf_event, moderator_client):
        challenges = call_json(moderator_client, "get", "api_challenge_list", kwargs={"event_id": ctf_event.id})
        assert challenges.status_code == 403
        staff = call_json(moderator_client, "get", "api_event_staff", kwargs={"event_id": ctf_event.id})
        assert staff.status_code == 403


class TestJudgeCapabilities:
    @pytest.fixture
    def judge_client(self, ctf_event, authenticated_organizer_client, helper_client):
        _assign(authenticated_organizer_client, ctf_event, "helper@test.com", "judge")
        return helper_client

    @pytest.fixture
    def target_participant(self, ctf_event, participant_user):
        from django.utils import timezone

        from ctf.models import CTFParticipant

        return CTFParticipant.objects.create(
            event=ctf_event,
            user=participant_user,
            email=participant_user.email,
            name="Scored Player",
            status="active",
            registered_at=timezone.now(),
        )

    def test_judge_grants_awards_but_cannot_manage_roster(self, ctf_event, judge_client, target_participant):
        granted = call_json(
            judge_client,
            "post",
            "api_participant_awards",
            kwargs={"participant_id": target_participant.id},
            body={"points": 25, "reason": "style points"},
        )
        assert granted.status_code == 201

        roster = call_json(judge_client, "get", "api_participant_list", kwargs={"event_id": ctf_event.id})
        assert roster.status_code == 403
        banned = call_json(
            judge_client, "post", "api_participant_ban", kwargs={"participant_id": target_participant.id}
        )
        assert banned.status_code == 403

    def test_judge_reads_participant_detail_and_timeline(self, judge_client, target_participant):
        detail = call_json(
            judge_client, "get", "api_participant_detail", kwargs={"participant_id": target_participant.id}
        )
        assert detail.status_code == 200
        timeline = call_json(
            judge_client, "get", "api_score_timeline", kwargs={"participant_id": target_participant.id}
        )
        assert timeline.status_code == 200
