"""Tests for provisioner status vocabulary in events.py."""

from __future__ import annotations

import pytest
from shared.enums import ResourceStatus


@pytest.mark.parametrize(
    ("alias", "status"),
    [
        ("STATUS_PENDING", ResourceStatus.PENDING),
        ("STATUS_PROVISIONING", ResourceStatus.PROVISIONING),
        ("STATUS_READY", ResourceStatus.READY),
        ("STATUS_PAUSING", ResourceStatus.PAUSING),
        ("STATUS_PAUSED", ResourceStatus.PAUSED),
        ("STATUS_RESUMING", ResourceStatus.RESUMING),
        ("STATUS_FAILED", ResourceStatus.FAILED),
        ("STATUS_DESTROYING", ResourceStatus.DESTROYING),
        ("STATUS_DESTROYED", ResourceStatus.DESTROYED),
    ],
)
def test_status_aliases_match_cyberscript_enum(alias: str, status: ResourceStatus):
    import events as provisioner_events

    assert getattr(provisioner_events, alias) == status.value
