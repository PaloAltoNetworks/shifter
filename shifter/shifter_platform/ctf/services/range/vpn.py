"""Participant OpenVPN profile retrieval through the CTF service boundary."""

from __future__ import annotations

from uuid import UUID

from ctf.services.range.status import _get_participant_with_range
from shared.remote_access import OpenVpnProfile


def get_vpn_profile(participant_id: UUID) -> OpenVpnProfile:
    """Resolve the current participant-owned profile; accept no caller target ids."""
    from ctf.bridges import cms_get_openvpn_profile

    participant = _get_participant_with_range(participant_id)
    assert participant.user is not None
    assert participant.range_instance_id is not None
    return cms_get_openvpn_profile(participant.user, participant.range_instance_id)
