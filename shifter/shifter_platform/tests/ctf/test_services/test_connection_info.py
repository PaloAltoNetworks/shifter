"""Tests for per-challenge connection info resolution (CTF-115).

Integration-style tests using real DB objects. CMS bridge is mocked
since it requires a running engine/range infrastructure.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from ctf.enums import (
    ChallengeCategory,
    ChallengeDifficulty,
    EventStatus,
    ParticipantStatus,
)
from ctf.models import CTFChallenge, CTFEvent, CTFParticipant

MOCK_INSTANCES = [
    {"name": "windows-target", "private_ip": "10.0.1.10", "os_type": "windows", "role": "victim"},
    {"name": "linux-web", "private_ip": "10.0.1.20", "os_type": "linux", "role": "victim"},
]


@pytest.fixture
def active_event(db, organizer_user):
    """Active event for connection info tests."""
    return CTFEvent.objects.create(
        name="Connection Info Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
    )


@pytest.fixture
def challenge_with_target(db, active_event):
    """Challenge targeting a specific instance and port."""
    return CTFChallenge.objects.create(
        event=active_event,
        name="RDP Challenge",
        description="Gain access to the Windows target via RDP",
        category=ChallengeCategory.NETWORK.value,
        points=200,
        difficulty=ChallengeDifficulty.MEDIUM.value,
        flag_hash="$2b$12$placeholder",
        target_instance_name="windows-target",
        target_port=3389,
    )


@pytest.fixture
def challenge_no_target(db, active_event):
    """Challenge without connection info."""
    return CTFChallenge.objects.create(
        event=active_event,
        name="OSINT Challenge",
        description="Find the hidden information",
        category=ChallengeCategory.OSINT.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$placeholder2",
    )


@pytest.fixture
def challenge_no_port(db, active_event):
    """Challenge with instance target but no port."""
    return CTFChallenge.objects.create(
        event=active_event,
        name="Web Challenge",
        description="Exploit the web server",
        category=ChallengeCategory.WEB.value,
        points=150,
        difficulty=ChallengeDifficulty.MEDIUM.value,
        flag_hash="$2b$12$placeholder3",
        target_instance_name="linux-web",
    )


@pytest.fixture
def challenge_unmatched(db, active_event):
    """Challenge referencing an instance name that doesn't exist in the range."""
    return CTFChallenge.objects.create(
        event=active_event,
        name="Missing Target",
        description="Target that does not exist",
        category=ChallengeCategory.MISC.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$placeholder4",
        target_instance_name="nonexistent-host",
        target_port=22,
    )


@pytest.fixture
def participant_with_range(db, active_event, participant_user):
    """Participant with a ready range."""
    return CTFParticipant.objects.create(
        event=active_event,
        user=participant_user,
        email=participant_user.email,
        name="Connection Info Participant",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
        range_instance_id=42,
        range_status="ready",
    )


def _resolve_connection_info(challenge, participant):
    """Helper: replicates the view's connection info resolution logic."""
    if not challenge.target_instance_name:
        return None
    if participant.range_status != "ready" or not participant.user:
        return None

    from ctf.bridges import cms_get_target_instances

    instances = cms_get_target_instances(participant.user.pk)
    for inst in instances:
        if inst.get("name") == challenge.target_instance_name:
            return {
                "host": inst["private_ip"],
                "port": challenge.target_port,
                "instance_name": inst["name"],
                "os_type": inst.get("os_type", ""),
            }
    return None


@pytest.mark.django_db
class TestConnectionInfoResolution:
    """Tests for resolving per-challenge connection info from range instances."""

    @patch("ctf.bridges.cms_get_target_instances", return_value=MOCK_INSTANCES)
    def test_resolves_matching_instance(self, mock_get, participant_with_range, challenge_with_target):
        """Challenge with target_instance_name resolves to correct IP and port."""
        info = _resolve_connection_info(challenge_with_target, participant_with_range)

        assert info is not None
        assert info["host"] == "10.0.1.10"
        assert info["port"] == 3389
        assert info["instance_name"] == "windows-target"
        assert info["os_type"] == "windows"

    @patch("ctf.bridges.cms_get_target_instances", return_value=MOCK_INSTANCES)
    def test_no_connection_info_without_target(self, mock_get, participant_with_range, challenge_no_target):
        """Challenge without target_instance_name returns None."""
        info = _resolve_connection_info(challenge_no_target, participant_with_range)

        assert info is None
        mock_get.assert_not_called()

    @patch("ctf.bridges.cms_get_target_instances", return_value=MOCK_INSTANCES)
    def test_unmatched_instance_returns_none(self, mock_get, participant_with_range, challenge_unmatched):
        """Challenge referencing nonexistent instance returns None."""
        info = _resolve_connection_info(challenge_unmatched, participant_with_range)

        assert info is None

    @patch("ctf.bridges.cms_get_target_instances", return_value=MOCK_INSTANCES)
    def test_port_none_when_not_set(self, mock_get, participant_with_range, challenge_no_port):
        """Connection info includes None port when target_port is not set."""
        info = _resolve_connection_info(challenge_no_port, participant_with_range)

        assert info is not None
        assert info["host"] == "10.0.1.20"
        assert info["port"] is None
        assert info["instance_name"] == "linux-web"

    @patch("ctf.bridges.cms_get_target_instances", return_value=MOCK_INSTANCES)
    def test_no_resolution_when_range_not_ready(
        self,
        mock_get,
        active_event,
        participant_user,
        challenge_with_target,
        db,
    ):
        """Connection info not resolved when participant's range is not ready."""
        participant = CTFParticipant.objects.create(
            event=active_event,
            user=participant_user,
            email=participant_user.email,
            name="No Range Participant",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
            range_status="provisioning",
        )
        info = _resolve_connection_info(challenge_with_target, participant)

        assert info is None
        mock_get.assert_not_called()
