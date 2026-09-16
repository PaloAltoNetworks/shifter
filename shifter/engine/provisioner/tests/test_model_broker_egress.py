"""Effective firewall semantics of the explicit model-broker capability."""

from __future__ import annotations

import ipaddress

import pytest

from config import GCERangeCellConfig
from gcp_range_cell_firewall import build_firewall_plan
from gcp_range_cell_types import GceEgressPolicy

VIP = "10.40.0.25"


def config():
    return GCERangeCellConfig(
        project_id="platform-example",
        region="us-central1",
        zone="us-central1-a",
        network_mode="shared-vpc",
        private_google_access=False,
        model_broker_vip=VIP,
    )


def capability():
    return {"contract_version": "model-broker-egress/v1", "vip": VIP, "port": 443}


def allows(rules, ip, port):
    for rule in sorted(rules, key=lambda item: item["priority"]):
        if rule["direction"] != "EGRESS":
            continue
        if not any(
            ipaddress.ip_address(ip) in ipaddress.ip_network(cidr) for cidr in rule.get("destination_ranges", [])
        ):
            continue
        for action in ("allowed", "denied"):
            for protocol in rule.get(action, []):
                if protocol["IPProtocol"] not in {"all", "tcp"}:
                    continue
                if "ports" not in protocol or str(port) in protocol["ports"]:
                    return action == "allowed"
    return False


def test_only_explicit_broker_host_and_tls_port_are_open():
    rules = build_firewall_plan(42, [], config(), egress_policy=GceEgressPolicy(model_broker=capability()))
    assert allows(rules, VIP, 443)
    for ip, port in [(VIP, 80), (VIP, 8444), ("10.40.0.26", 443), ("10.50.2.1", 443), ("169.254.169.254", 80)]:
        assert not allows(rules, ip, port)


def test_no_capability_means_no_broker_exception():
    assert not allows(build_firewall_plan(42, [], config()), VIP, 443)


def test_intra_range_allow_cannot_expose_other_broker_ports():
    cfg = config()
    policy = GceEgressPolicy(model_broker=capability())
    with pytest.raises(RuntimeError, match="overlap"):
        build_firewall_plan(42, [{"cidr": "10.40.0.0/24"}], cfg, egress_policy=policy)


@pytest.mark.parametrize("mutation", ["zero", "port", "vip", "forwarding", "service_account", "pga", "bypass"])
def test_unsafe_client_or_capability_is_rejected(mutation, monkeypatch):
    from dataclasses import replace

    cfg, cap, mode, instances = config(), capability(), "deny-all", []
    if mutation == "zero":
        mode = "none"
    elif mutation == "port":
        cap["port"] = 80
    elif mutation == "vip":
        cap["vip"] = "10.40.0.0/24"
    elif mutation == "forwarding":
        instances = [{"can_ip_forward": True}]
    elif mutation == "service_account":
        instances = [{"attach_service_account": True}]
    elif mutation == "pga":
        cfg = replace(cfg, private_google_access=True)
    else:
        monkeypatch.setenv("GCP_RANGE_PREPROVISIONED_FIREWALLS", "true")
    policy = GceEgressPolicy(mode=mode, model_broker=cap)
    with pytest.raises((ValueError, RuntimeError)):
        build_firewall_plan(42, [], cfg, egress_policy=policy, instance_plans=instances)


def _render_broker_plan(builder, cap, *, egress_mode="deny-all", pga=False, vip=VIP):
    from dataclasses import replace

    from gcp_range_cell_plan import render_range_cell_plan
    from raes_gcp_plan import build_raes_range_cell_plan

    from .test_gcp_range_cells import _sample_config, _variables
    from .test_raes_gcp_plan import _config, _network, _node, _plan, _resolver

    policy = GceEgressPolicy(mode=egress_mode, model_broker=cap)
    if builder == "range_spec":
        cfg = replace(_sample_config(), private_google_access=pga, model_broker_vip=vip)
        plan = render_range_cell_plan(
            "req-123",
            _variables(egress_mode=egress_mode),
            cfg,
            egress_policy=policy,
        )
    else:
        cfg = replace(_config(), private_google_access=pga, model_broker_vip=vip)
        plan = build_raes_range_cell_plan(
            "req-123",
            42,
            _plan((_node(),), (_network(),)),
            _resolver(),
            cfg,
            egress_policy=policy,
        )
    return plan


@pytest.mark.parametrize("builder", ["range_spec", "raes"])
@pytest.mark.parametrize("admitted", [False, True])
def test_real_plan_builders_realize_only_explicit_broker_capability(builder, admitted):
    plan = _render_broker_plan(builder, capability() if admitted else None)
    rules = plan["firewalls"]
    assert allows(rules, VIP, 443) is admitted
    for ip, port in [(VIP, 80), (VIP, 8444), ("10.40.0.26", 443), ("169.254.169.254", 80)]:
        assert not allows(rules, ip, port)


@pytest.mark.parametrize("builder", ["range_spec", "raes"])
@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"egress_mode": "none"}, "incompatible_egress"),
        ({"pga": True}, "source-preserving keyless isolated egress"),
        ({"vip": "10.40.0.26"}, "broker_destination_mismatch"),
    ],
)
def test_real_plan_builders_reject_incompatible_broker_binding(builder, kwargs, error):
    cap = capability()
    with pytest.raises((ValueError, RuntimeError), match=error):
        _render_broker_plan(builder, cap, **kwargs)
