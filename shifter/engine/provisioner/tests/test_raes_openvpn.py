"""Participant OpenVPN access on the RAES GCE path (#2030, #2480, ADR-039-R10).

Drives ``raes_openvpn``: the installation must have a deployed shared pool, the
capability must name exactly one realized member, the pool rule is planned from
private pool networks only, and the profile is minted against the tenant CA.
The provider secret store is an in-memory double.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from shared.raes.operation_input import RaesRemoteAccess
from shared.remote_access import build_openvpn_capability

import raes_openvpn
from raes_gcp_network_allocation import RaesRealizationError
from raes_gcp_vpn_plan import RaesGceVpnAccess

_REQUEST_ID = "11111111-2222-3333-4444-555555555555"
_TARGET = "provision.node.kali#0"


@pytest.fixture
def pool(monkeypatch, vpn_secret_ops):
    """A deployed pool whose secret store is the in-memory double."""
    monkeypatch.setattr(raes_openvpn, "GCPVpnSecretOps", lambda: vpn_secret_ops)
    monkeypatch.setattr(raes_openvpn, "openvpn_access_enabled", lambda: True)
    monkeypatch.setenv("RANGE_OPENVPN_ENDPOINT", "203.0.113.7")
    monkeypatch.setenv("RANGE_OPENVPN_POOL_CIDRS", "10.49.0.0/24")
    return vpn_secret_ops


def _remote(target: str = _TARGET) -> RaesRemoteAccess:
    return RaesRemoteAccess(capability=build_openvpn_capability(target, datetime.now(UTC) + timedelta(days=1)))


def _plan():
    kali = SimpleNamespace(address="provision.node.kali", count=1)
    victims = SimpleNamespace(address="provision.node.victim", count=2)
    return SimpleNamespace(nodes=(kali, victims))


class TestPrepare:
    def test_a_range_without_remote_access_prepares_nothing(self, pool):
        assert raes_openvpn.prepare_raes_openvpn(_REQUEST_ID, 7, _plan(), None) is None

    def test_an_installation_without_a_pool_fails_closed(self, monkeypatch, pool):
        monkeypatch.setattr(raes_openvpn, "openvpn_access_enabled", lambda: False)
        with pytest.raises(RaesRealizationError, match="no shared OpenVPN pool"):
            raes_openvpn.prepare_raes_openvpn(_REQUEST_ID, 7, _plan(), _remote())

    def test_a_target_outside_the_plan_fails_closed(self, pool):
        with pytest.raises(RaesRealizationError, match="exactly one range member"):
            raes_openvpn.prepare_raes_openvpn(_REQUEST_ID, 7, _plan(), _remote("provision.node.dc#0"))

    @pytest.mark.parametrize("cidrs", ["", "0.0.0.0/0", "8.8.8.0/24", "10.0.0.0/8"])
    def test_pool_networks_must_be_narrow_and_private(self, monkeypatch, pool, cidrs):
        # An ingress rule without a source would admit every address.
        monkeypatch.setenv("RANGE_OPENVPN_POOL_CIDRS", cidrs)
        with pytest.raises(RaesRealizationError):
            raes_openvpn.prepare_raes_openvpn(_REQUEST_ID, 7, _plan(), _remote())

    def test_prepared_access_plans_the_pool_rule_and_mints_on_publish(self, pool):
        prepared = raes_openvpn.prepare_raes_openvpn(_REQUEST_ID, 7, _plan(), _remote())

        assert prepared.plan_access() == RaesGceVpnAccess(target_ref=_TARGET, pool_cidrs=("10.49.0.0/24",))
        assert pool.profiles == {}
        realization = prepared.publish()
        assert realization["target_ref"] == _TARGET
        assert realization["endpoint"] == "203.0.113.7"
        assert (7, _REQUEST_ID) in pool.profiles


class TestCleanup:
    def test_destroy_names_and_profile_deletion(self, pool):
        assert raes_openvpn.vpn_access_names(_remote()) == RaesGceVpnAccess(target_ref=_TARGET)
        assert raes_openvpn.vpn_access_names(None) is None

        raes_openvpn.cleanup_raes_openvpn(_REQUEST_ID, 7, _remote())
        raes_openvpn.cleanup_raes_openvpn(_REQUEST_ID, 7, None)

        assert pool.deleted == [(7, _REQUEST_ID)]

    def test_failed_provision_cleanup_never_masks_the_failure(self, monkeypatch, pool):
        def boom():
            raise RuntimeError("secret store down")

        monkeypatch.setattr(raes_openvpn, "GCPVpnSecretOps", boom)
        raes_openvpn.cleanup_failed_provision_openvpn(_REQUEST_ID, 7, _remote())

    def test_result_fragment(self):
        assert raes_openvpn.vpn_access_fragment(None) == {}
        assert raes_openvpn.vpn_access_fragment({"a": 1}) == {"vpn_access": {"a": 1}}
