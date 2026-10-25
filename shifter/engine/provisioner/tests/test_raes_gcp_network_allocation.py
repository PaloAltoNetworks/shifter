"""RAES shared-VPC network allocation projection tests (#2219)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import raes_gcp_network_allocation
from raes_gcp_network_allocation import (
    RaesRealizationError,
    allocated_networks_for_destroy,
    allocated_networks_for_provision,
)
from raes_plan import RaesPlan, RaesPlanNetwork, RaesPlanNode

_REQUEST_ID = "11111111-1111-1111-1111-111111111111"
_OPERATION_ID = "22222222-2222-2222-2222-222222222222"


def _plan(*networks: RaesPlanNetwork, open_network: bool = False) -> RaesPlan:
    node = RaesPlanNode(
        address="node.web",
        name="web",
        os_family="linux",
        count=1,
        network_addresses=() if open_network else (networks[0].address,),
        network_selection_open=open_network,
    )
    return RaesPlan(raes_version="3.5.0", nodes=(node,), networks=networks)


def _config() -> SimpleNamespace:
    return SimpleNamespace(network_mode="shared-vpc")


@pytest.fixture
def allocation_fakes(monkeypatch):
    reserve = MagicMock(return_value=("10.50.2.0/24",))
    read = MagicMock(return_value=("10.50.2.0/24",))
    monkeypatch.setattr(raes_gcp_network_allocation, "reserve_range_subnets", reserve)
    monkeypatch.setattr(raes_gcp_network_allocation, "read_range_subnets", read)
    monkeypatch.setattr(
        raes_gcp_network_allocation,
        "load_range_network_config",
        lambda: SimpleNamespace(
            network_id="projects/range/global/networks/shared",
            network_cidr="10.50.0.0/16",
        ),
    )
    return reserve, read


def test_fixed_authored_network_is_reserved_from_tenant_supernet(allocation_fakes):
    reserve, _read = allocation_fakes
    plan = _plan(RaesPlanNetwork(address="provision.network.lan", name="lan", cidr="10.50.0.0/24"))

    allocation = allocated_networks_for_provision(_REQUEST_ID, _OPERATION_ID, plan, _config())

    assert allocation.require_available() == (("provision.network.lan", "10.50.2.0/24"),)
    reserve.assert_called_once_with(
        operation_id=_OPERATION_ID,
        request_id=_REQUEST_ID,
        network_id="projects/range/global/networks/shared",
        network_cidr="10.50.0.0/16",
        subnets=("provision.network.lan",),
        prefix_length=24,
    )


def test_fixed_and_open_networks_share_one_atomic_batch(allocation_fakes):
    reserve, _read = allocation_fakes
    reserve.return_value = ("10.50.2.0/24", "10.50.3.0/24")
    plan = _plan(
        RaesPlanNetwork(address="provision.network.lan", name="lan", cidr="10.50.0.0/24"),
        open_network=True,
    )

    allocation = allocated_networks_for_provision(_REQUEST_ID, _OPERATION_ID, plan, _config())

    assert allocation.require_available() == (
        ("provision.network.lan", "10.50.2.0/24"),
        ("backend.gce.network.default", "10.50.3.0/24"),
    )
    assert reserve.call_args.kwargs["subnets"] == (
        "provision.network.lan",
        "backend.gce.network.default",
    )
    assert reserve.call_args.kwargs["prefix_length"] == 24


def test_multiple_fixed_networks_share_one_atomic_batch(allocation_fakes):
    reserve, _read = allocation_fakes
    reserve.return_value = ("10.50.2.0/24", "10.50.3.0/24")
    plan = _plan(
        RaesPlanNetwork(address="provision.network.lan", name="lan", cidr="10.50.0.0/24"),
        RaesPlanNetwork(address="provision.network.dmz", name="dmz", cidr="10.50.1.0/24"),
    )

    allocation = allocated_networks_for_provision(_REQUEST_ID, _OPERATION_ID, plan, _config())

    assert allocation.network_cidrs == (
        ("provision.network.lan", "10.50.2.0/24"),
        ("provision.network.dmz", "10.50.3.0/24"),
    )
    reserve.assert_called_once()


def test_mixed_authored_prefixes_fail_before_reservation(allocation_fakes):
    reserve, _read = allocation_fakes
    plan = _plan(
        RaesPlanNetwork(address="provision.network.lan", name="lan", cidr="10.50.0.0/24"),
        RaesPlanNetwork(address="provision.network.dmz", name="dmz", cidr="10.50.1.0/28"),
    )

    with pytest.raises(RaesRealizationError, match="same supported prefix"):
        allocated_networks_for_provision(_REQUEST_ID, _OPERATION_ID, plan, _config())

    reserve.assert_not_called()


def test_destroy_reconstructs_the_same_ordered_projection(allocation_fakes):
    _reserve, read = allocation_fakes
    read.return_value = ("10.50.2.0/24", "10.50.3.0/24")
    plan = _plan(
        RaesPlanNetwork(address="provision.network.lan", name="lan", cidr="10.50.0.0/24"),
        open_network=True,
    )

    allocation = allocated_networks_for_destroy(_REQUEST_ID, _OPERATION_ID, plan, _config())

    assert allocation.network_cidrs == (
        ("provision.network.lan", "10.50.2.0/24"),
        ("backend.gce.network.default", "10.50.3.0/24"),
    )
    read.assert_called_once_with(operation_id=_OPERATION_ID, request_id=_REQUEST_ID)


def test_vpc_per_range_does_not_reach_shared_allocator(allocation_fakes):
    reserve, read = allocation_fakes
    plan = _plan(RaesPlanNetwork(address="provision.network.lan", name="lan", cidr="10.50.0.0/24"))
    config = SimpleNamespace(network_mode="vpc-per-range")

    allocation = allocated_networks_for_provision(_REQUEST_ID, _OPERATION_ID, plan, config)

    assert allocation.required is False
    assert allocation.require_available() is None
    reserve.assert_not_called()
    read.assert_not_called()
