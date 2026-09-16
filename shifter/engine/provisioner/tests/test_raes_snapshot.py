"""Tests for the bounded RAES runtime-snapshot resources reducer (ADR-031-R4)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from raes_plan import (
    RaesPlan,
    RaesPlanAccount,
    RaesPlanContent,
    RaesPlanFeature,
    RaesPlanNetwork,
    RaesPlanNode,
)
from raes_snapshot import snapshot_resources


def _plan() -> RaesPlan:
    node = RaesPlanNode(
        address="provision.node.web", name="web", os_family="linux", count=1, network_addresses=("net.a",)
    )
    network = RaesPlanNetwork(address="provision.network.a", name="a", cidr="10.0.0.0/24")
    return RaesPlan(raes_version="3.5.0", nodes=(node,), networks=(network,))


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
    assert snapshot_resources(RaesPlan(raes_version="3.5.0", nodes=(), networks=())) == []


def _composition_plan() -> RaesPlan:
    base = _plan()
    return RaesPlan(
        raes_version=base.raes_version,
        nodes=base.nodes,
        networks=base.networks,
        content=(
            RaesPlanContent(
                address="content.seed",
                name="seed",
                content_type="directory",
                target_address="provision.node.web",
                destination="/srv/seed",
            ),
        ),
        accounts=(
            RaesPlanAccount(
                address="account.operator",
                username="operator",
                target_address="provision.node.web",
            ),
        ),
        features=(
            RaesPlanFeature(
                address="feature.config",
                name="config",
                feature_type="configuration",
                target_address="provision.node.web",
                source_name="config",
                destination="/etc/config",
            ),
        ),
    )


def test_adds_only_exactly_verified_composition_resources():
    resources = snapshot_resources(
        _composition_plan(),
        {"content.seed", "account.operator", "feature.config"},
    )
    assert resources[-3:] == [
        {"address": "content.seed", "resource_type": "content-placement", "status": "verified"},
        {"address": "account.operator", "resource_type": "account-placement", "status": "verified"},
        {"address": "feature.config", "resource_type": "feature-binding", "status": "verified"},
    ]


@pytest.mark.parametrize(
    "verified",
    [
        {"content.seed", "account.operator"},
        {"content.seed", "account.operator", "feature.config", "content.extra"},
    ],
)
def test_rejects_missing_or_extra_composition_proof(verified):
    plan = _composition_plan()
    with pytest.raises(ValueError, match="composition verification coverage"):
        snapshot_resources(plan, verified)


def test_rejects_complete_snapshot_that_exceeds_persistence_bound():
    base = _plan()
    content = tuple(
        RaesPlanContent(
            address=f"content.{index}." + "x" * 80,
            name=f"content-{index}",
            content_type="directory",
            target_address="provision.node.web",
            destination=f"/srv/{index}",
        )
        for index in range(700)
    )
    plan = RaesPlan(
        raes_version=base.raes_version,
        nodes=base.nodes,
        networks=base.networks,
        content=content,
    )
    verified = {item.address for item in content}

    with pytest.raises(ValueError, match="size bound"):
        snapshot_resources(plan, verified)
