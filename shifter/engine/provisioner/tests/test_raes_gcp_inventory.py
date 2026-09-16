"""Post-teardown provider inventory/readback of RAES range cells (#2086, ADR-063-R4/R5)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from config import GCERangeCellConfig
from raes_gcp_inventory import INCOMPLETE, RESIDUALS_FOUND, VERIFIED_ABSENT, inventory_raes_range_cell
from raes_plan import RaesPlan, RaesPlanImage, RaesPlanNetwork, RaesPlanNode

_REQUEST = "11111111-1111-1111-1111-111111111111"


class _NotFound(Exception):
    """Fake Google NotFound exception."""


def _config() -> GCERangeCellConfig:
    return GCERangeCellConfig(
        project_id="proj-1",
        region="us-east1",
        zone="us-east1-b",
        network_mode="vpc-per-range",
        network_id="",
        service_account_email="host@proj-1.iam.gserviceaccount.com",
        portal_network_cidrs=("203.0.113.0/24",),
    )


def _plan() -> RaesPlan:
    node = RaesPlanNode(
        address="node.web",
        name="web",
        os_family="linux",
        count=1,
        network_addresses=("net.lan",),
        image=RaesPlanImage(name="ubuntu"),
    )
    network = RaesPlanNetwork(address="net.lan", name="lan", cidr="10.9.0.0/24")
    return RaesPlan(raes_version="2.0.0", nodes=(node,), networks=(network,))


def _clients(*, exists: bool = False, get_error: Exception | None = None) -> SimpleNamespace:
    def get_side_effect(**_kwargs):
        if get_error is not None:
            raise get_error
        if exists:
            return SimpleNamespace(name="resource")
        raise _NotFound()

    def service() -> MagicMock:
        svc = MagicMock()
        svc.get.side_effect = get_side_effect
        return svc

    return SimpleNamespace(
        networks=service(),
        subnetworks=service(),
        firewalls=service(),
        addresses=service(),
        routers=service(),
        instances=service(),
        google_exceptions=SimpleNamespace(NotFound=_NotFound),
    )


def test_all_resources_absent_is_verified():
    result = inventory_raes_range_cell(_REQUEST, 7, _plan(), config=_config(), clients=_clients(exists=False))
    assert result["outcome"] == VERIFIED_ABSENT
    assert result["residual_categories"] == []
    assert result["scope"]["project"] == "proj-1"


def test_present_resources_are_residuals():
    result = inventory_raes_range_cell(_REQUEST, 7, _plan(), config=_config(), clients=_clients(exists=True))
    assert result["outcome"] == RESIDUALS_FOUND
    assert result["residual_categories"]


def test_provider_error_is_incomplete_not_empty_success():
    result = inventory_raes_range_cell(
        _REQUEST, 7, _plan(), config=_config(), clients=_clients(get_error=RuntimeError("api down"))
    )
    assert result["outcome"] == INCOMPLETE
