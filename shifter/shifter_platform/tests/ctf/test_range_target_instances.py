"""Participant-safe target-instance projection for CTF range access (issue #1740).

The SPA workspace renders per-box access from the CTF range-status API. The CTF
bridge must project CMS instances down to the {uuid, name, private_ip, os_type}
allowlist so range-internal metadata (roles, provider details, channel bindings,
secret references) never crosses into the participant surface, and the status
service must only expose targets once the range is ready.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import ctf.bridges as bridges
from ctf.services.participant.accounts import create_participant_accounts
from ctf.services.range.status import get_range_status

_PROJECTED = {"uuid": "u1", "name": "dc01", "private_ip": "10.1.2.56", "os_type": "windows"}


def test_bridge_projects_instances_to_safe_allowlist(monkeypatch):
    # CMS returns rich dicts; the bridge must drop everything outside the allowlist.
    raw = [
        {
            **_PROJECTED,
            "role": "target",
            "rdp_password": "super-secret",
            "provider": "aws",
            "channel_binding": "participant-a",
            "range_instance_id": 42,
        }
    ]
    monkeypatch.setattr("cms.services.get_range_target_instances", lambda _user_id: raw)

    result = bridges.cms_get_range_target_instances(SimpleNamespace(pk=7))

    assert result == [_PROJECTED]
    # No leaked keys — the projection is the security boundary, not the serializer.
    assert set(result[0]) == {"uuid", "name", "private_ip", "os_type"}


@pytest.mark.django_db
def test_range_status_exposes_targets_only_when_ready(ctf_event_active, monkeypatch):
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    monkeypatch.setattr("ctf.bridges.cms_has_openvpn_profile", lambda *_a, **_kw: False)
    monkeypatch.setattr("ctf.bridges.cms_get_range_target_instances", lambda _user: [dict(_PROJECTED)])
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    participant.range_instance_id = 42
    participant.range_status = "ready"
    participant.save(update_fields=["range_instance_id", "range_status"])

    monkeypatch.setattr("ctf.bridges.cms_get_range_status", lambda _rid: "ready")
    ready = get_range_status(participant.pk)

    assert ready["status"] == "ready"
    assert ready["target_instances"] == [_PROJECTED]

    # A provisioning range must not leak targets.
    monkeypatch.setattr("ctf.bridges.cms_get_range_status", lambda _rid: "provisioning")
    provisioning = get_range_status(participant.pk)

    assert provisioning["status"] == "provisioning"
    assert provisioning["target_instances"] == []
