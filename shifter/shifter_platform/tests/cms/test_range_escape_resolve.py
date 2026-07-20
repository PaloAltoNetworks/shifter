"""Executed coverage for range resolution (issue #1347).

Participant selection decides whose network context the security probes launch
from, so it is security-relevant: probing from the wrong instance (for example a
domain controller instead of the participant attacker) would invalidate the
participant-controlled-context guarantee. These tests execute the real selection
and RangeUnderTest construction (the engine.services membership seam is faked).
"""

from __future__ import annotations

import pytest

import engine.services
from cms.range_escape.resolve import (
    RangeResolutionError,
    _pick_participant_instance,
    resolve_range_under_test,
)
from engine.services import RangeMembership


def _attacker() -> dict[str, object]:
    return {
        "uuid": "attacker-uuid",
        "role": "attacker",
        "private_ip": "10.50.1.4",
        "ssh_key_secret_arn": "secret://ssh/attacker",
        "ssh_username": "kali",
        "gcp_host_ssh_port": 2222,
        "gcp_host_ssh_key_secret_ref": "secret://host/attacker",
        "gcp_host_ssh_username": "hostadmin",
        "gcp_host_public_key": "ssh-ed25519 AAAAATTACKER",
        "gcp_instance_name": "range-attacker",
        "gcp_zone": "us-central1-b",
        "gcp_project_id": "proj",
    }


def _dc() -> dict[str, object]:
    return {
        "uuid": "dc-uuid",
        "role": "dc",
        "private_ip": "10.50.1.5",
        "ssh_key_secret_arn": "secret://ssh/dc",
        "ssh_username": "Administrator",
        "gcp_instance_name": "range-dc",
        "gcp_zone": "us-central1-b",
        "gcp_project_id": "proj",
    }


class TestPickParticipant:
    def test_prefers_attacker_over_other_roles(self) -> None:
        chosen = _pick_participant_instance([_dc(), _attacker()])
        assert chosen["uuid"] == "attacker-uuid"

    def test_falls_back_to_any_instance_with_ssh_key(self) -> None:
        chosen = _pick_participant_instance([_dc()])
        assert chosen["uuid"] == "dc-uuid"

    def test_raises_when_no_instances(self) -> None:
        with pytest.raises(RangeResolutionError):
            _pick_participant_instance([])


class TestResolveRangeUnderTest:
    def _install_membership(self, monkeypatch: pytest.MonkeyPatch, membership: RangeMembership | None) -> None:
        monkeypatch.setattr(engine.services, "get_range_membership", lambda request_id: membership)

    def test_native_selects_attacker_and_derives_dns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        membership = RangeMembership(range_id=7, instances=(_dc(), _attacker()), subnet_cidrs=("10.50.1.0/28",))
        self._install_membership(monkeypatch, membership)

        rut = resolve_range_under_test(request_id="req-7", adapter="native")

        assert rut.range_id == 7
        assert rut.participant.target_ref == "attacker-uuid"
        assert rut.participant.address == "10.50.1.4"
        assert rut.participant.ssh_port == 22
        assert rut.participant.credential_ref == "secret://ssh/attacker"
        assert rut.participant.host_public_key == "ssh-ed25519 AAAAATTACKER"
        assert set(rut.member_ips) == {"10.50.1.4", "10.50.1.5"}
        # Peer-owned DNS identities are derived from member instance metadata.
        assert "range-attacker.us-central1-b.c.proj.internal" in rut.dns_names

    def test_polaris_uses_host_ssh_channel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        membership = RangeMembership(range_id=7, instances=(_attacker(),), subnet_cidrs=("10.50.1.0/28",))
        self._install_membership(monkeypatch, membership)

        rut = resolve_range_under_test(request_id="req-7", adapter="polaris", container="a14-kali")

        assert rut.participant.ssh_port == 2222
        assert rut.participant.credential_ref == "secret://host/attacker"
        assert rut.participant.username == "hostadmin"
        assert rut.participant.container == "a14-kali"

    def test_missing_range_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._install_membership(monkeypatch, None)
        with pytest.raises(RangeResolutionError, match="no range found"):
            resolve_range_under_test(request_id="req-missing")

    def test_participant_without_ssh_credential_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        no_cred = {"uuid": "x", "role": "attacker", "private_ip": "10.50.1.4"}
        membership = RangeMembership(range_id=7, instances=(no_cred,), subnet_cidrs=("10.50.1.0/28",))
        self._install_membership(monkeypatch, membership)
        with pytest.raises(RangeResolutionError, match="SSH credential"):
            resolve_range_under_test(request_id="req-7")
