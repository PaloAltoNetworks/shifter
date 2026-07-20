"""Tests for the bounded ACES runtime-snapshot resources reducer (ADR-031-R4)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from aces_plan import AcesPlan, AcesPlanNetwork, AcesPlanNode
from aces_snapshot import snapshot_resources


def _plan() -> AcesPlan:
    node = AcesPlanNode(
        address="provision.node.web", name="web", os_family="linux", count=1, network_addresses=("net.a",)
    )
    network = AcesPlanNetwork(address="provision.network.a", name="a", cidr="10.0.0.0/24")
    return AcesPlan(aces_sdl_version="0.19.1", nodes=(node,), networks=(network,))


def test_reduces_to_bounded_address_type_status():
    resources = snapshot_resources(_plan())
    assert resources == [
        {"address": "provision.network.a", "resource_type": "network", "status": "provisioned"},
        {"address": "provision.node.web", "resource_type": "node", "status": "provisioned"},
    ]


def test_carries_no_infrastructure_detail():
    # Only address/resource_type/status keys -> no cidr/subnet/secret leakage.
    for entry in snapshot_resources(_plan()):
        assert set(entry) == {"address", "resource_type", "status"}


def test_empty_plan_yields_no_resources():
    assert snapshot_resources(AcesPlan(aces_sdl_version="0.19.1", nodes=(), networks=())) == []
