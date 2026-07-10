"""Tests for assert_portal_inspection.py.

Run via the package's uv environment from the repo root:
    cd scripts/assert_portal_inspection && uv run pytest tests/ -v
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assert_portal_inspection import (
    evaluate_inspection,
    load_contract,
    main,
)

AZS = ["us-east-2a", "us-east-2b"]
EP = {"us-east-2a": "vpce-aaa", "us-east-2b": "vpce-bbb"}
PUB_CIDRS = ["10.0.0.0/20", "10.0.16.0/20"]
PRIV_CIDRS = ["10.0.32.0/20", "10.0.48.0/20"]
FW_CIDRS = ["10.0.255.0/28", "10.0.255.16/28"]
PUB_RT = ["rtb-pub-a", "rtb-pub-b"]
PRIV_RT = ["rtb-priv-a", "rtb-priv-b"]
FW_RT = ["rtb-fw-a", "rtb-fw-b"]
NAT = "nat-0123456789"
ARN = "arn:aws:network-firewall:us-east-2:111122223333:firewall/dev-portal-firewall"
VPC_CIDR = "10.0.0.0/16"


def _contract(enabled: bool = True) -> dict:
    if not enabled:
        return {
            "inspection_enabled": False,
            "firewall_arn": "",
            "availability_zones": AZS,
            "endpoint_ids_by_az": {},
            "public_route_table_ids": PUB_RT,
            "private_route_table_ids": PRIV_RT,
            "firewall_route_table_ids": [],
            "public_subnet_cidrs": PUB_CIDRS,
            "private_subnet_cidrs": PRIV_CIDRS,
            "firewall_subnet_cidrs": [],
            "nat_gateway_id": NAT,
        }
    return {
        "inspection_enabled": True,
        "firewall_arn": ARN,
        "availability_zones": AZS,
        "endpoint_ids_by_az": dict(EP),
        "public_route_table_ids": PUB_RT,
        "private_route_table_ids": PRIV_RT,
        "firewall_route_table_ids": FW_RT,
        "public_subnet_cidrs": PUB_CIDRS,
        "private_subnet_cidrs": PRIV_CIDRS,
        "firewall_subnet_cidrs": FW_CIDRS,
        "nat_gateway_id": NAT,
    }


def _sync_states() -> dict:
    return {
        az: {
            "Attachment": {
                "SubnetId": f"subnet-fw-{i}",
                "EndpointId": EP[az],
                "Status": "READY",
            },
            "Config": {},
        }
        for i, az in enumerate(AZS)
    }


def _local_route() -> dict:
    return {"DestinationCidrBlock": VPC_CIDR, "GatewayId": "local", "State": "active"}


def _route_tables() -> list[dict]:
    tables: list[dict] = []
    for i, az in enumerate(AZS):
        ep = EP[az]
        # Public RT: reach every private subnet CIDR via the same-AZ endpoint.
        pub_routes = [_local_route()]
        for cidr in PRIV_CIDRS:
            pub_routes.append({"DestinationCidrBlock": cidr, "VpcEndpointId": ep, "State": "active"})
        tables.append({"RouteTableId": PUB_RT[i], "Routes": pub_routes})
        # Private RT: reach every public subnet CIDR plus 0.0.0.0/0 via same-AZ endpoint.
        priv_routes = [_local_route()]
        for cidr in PUB_CIDRS:
            priv_routes.append({"DestinationCidrBlock": cidr, "VpcEndpointId": ep, "State": "active"})
        priv_routes.append({"DestinationCidrBlock": "0.0.0.0/0", "VpcEndpointId": ep, "State": "active"})
        tables.append({"RouteTableId": PRIV_RT[i], "Routes": priv_routes})
        # Firewall RT: default route onward to the shared NAT gateway.
        fw_routes = [_local_route(), {"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": NAT, "State": "active"}]
        tables.append({"RouteTableId": FW_RT[i], "Routes": fw_routes})
    return tables


# --------------------------------------------------------------------------- #
# load_contract
# --------------------------------------------------------------------------- #


def test_load_contract_extracts_value() -> None:
    outputs = {"portal_inspection_assertion": {"value": _contract(), "type": "object"}}
    assert load_contract(outputs)["firewall_arn"] == ARN


def test_load_contract_missing_output_raises() -> None:
    with pytest.raises(RuntimeError, match="portal_inspection_assertion"):
        load_contract({"some_other_output": {"value": 1}})


# --------------------------------------------------------------------------- #
# evaluate_inspection — happy path
# --------------------------------------------------------------------------- #


def test_healthy_topology_passes() -> None:
    failures = evaluate_inspection(_contract(), _sync_states(), "IN_SYNC", _route_tables())
    assert failures == []


def _route_tables_gateway_form() -> list[dict]:
    """Mirror _route_tables() but report firewall-endpoint targets under
    GatewayId, the way live EC2 DescribeRouteTables returns a Gateway Load
    Balancer VPC endpoint (the Network Firewall endpoint) — "vpce-..." in
    GatewayId, not VpcEndpointId."""
    tables = _route_tables()
    for table in tables:
        for route in table["Routes"]:
            endpoint = route.pop("VpcEndpointId", None)
            if endpoint is not None:
                route["GatewayId"] = endpoint
    return tables


def test_healthy_topology_passes_with_gateway_endpoint_form() -> None:
    # Regression: firewall-endpoint routes surface under GatewayId in live
    # EC2 output; the assertion must recognize them there too.
    failures = evaluate_inspection(_contract(), _sync_states(), "IN_SYNC", _route_tables_gateway_form())
    assert failures == []


def test_prefix_list_gateway_endpoint_routes_are_ignored() -> None:
    # Regression: S3 / DynamoDB gateway VPC endpoints add prefix-list routes
    # (no CIDR destination) that also target a "vpce-..." gateway. They must
    # not be mistaken for firewall inspection routes pointing at the wrong
    # endpoint.
    tables = _route_tables_gateway_form()
    for table in tables:
        if table["RouteTableId"] in PRIV_RT:
            table["Routes"].append(
                {
                    "DestinationPrefixListId": "pl-s3example",
                    "GatewayId": "vpce-0000000000s3ddb",
                    "State": "active",
                }
            )
    failures = evaluate_inspection(_contract(), _sync_states(), "IN_SYNC", tables)
    assert failures == []


# --------------------------------------------------------------------------- #
# evaluate_inspection — firewall health
# --------------------------------------------------------------------------- #


def test_config_out_of_sync_fails() -> None:
    failures = evaluate_inspection(_contract(), _sync_states(), "PENDING", _route_tables())
    assert any("PENDING" in f for f in failures)


def test_unhealthy_attachment_fails() -> None:
    sync = _sync_states()
    sync["us-east-2b"]["Attachment"]["Status"] = "DELETING"
    failures = evaluate_inspection(_contract(), sync, "IN_SYNC", _route_tables())
    assert any("us-east-2b" in f and "DELETING" in f for f in failures)


def test_missing_sync_state_for_az_fails() -> None:
    sync = _sync_states()
    del sync["us-east-2b"]
    failures = evaluate_inspection(_contract(), sync, "IN_SYNC", _route_tables())
    assert any("us-east-2b" in f for f in failures)


def test_tf_live_endpoint_mismatch_fails() -> None:
    sync = _sync_states()
    sync["us-east-2a"]["Attachment"]["EndpointId"] = "vpce-stale"
    failures = evaluate_inspection(_contract(), sync, "IN_SYNC", _route_tables())
    assert any("vpce-stale" in f and "us-east-2a" in f for f in failures)


# --------------------------------------------------------------------------- #
# evaluate_inspection — route wiring
# --------------------------------------------------------------------------- #


def test_stale_route_endpoint_fails() -> None:
    rts = _route_tables()
    # Point one public-RT route at a wrong/stale endpoint.
    rts[0]["Routes"][1]["VpcEndpointId"] = "vpce-old"
    failures = evaluate_inspection(_contract(), _sync_states(), "IN_SYNC", rts)
    assert any("rtb-pub-a" in f and "vpce-old" in f for f in failures)


def test_private_default_via_nat_bypass_fails() -> None:
    rts = _route_tables()
    # Replace the private 0.0.0.0/0-via-firewall with a direct NAT bypass.
    priv_a = next(t for t in rts if t["RouteTableId"] == "rtb-priv-a")
    priv_a["Routes"] = [r for r in priv_a["Routes"] if r["DestinationCidrBlock"] != "0.0.0.0/0"]
    priv_a["Routes"].append({"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": NAT, "State": "active"})
    failures = evaluate_inspection(_contract(), _sync_states(), "IN_SYNC", rts)
    assert any("rtb-priv-a" in f and "0.0.0.0/0" in f for f in failures)


def test_missing_private_default_fails() -> None:
    rts = _route_tables()
    priv_b = next(t for t in rts if t["RouteTableId"] == "rtb-priv-b")
    priv_b["Routes"] = [r for r in priv_b["Routes"] if r["DestinationCidrBlock"] != "0.0.0.0/0"]
    failures = evaluate_inspection(_contract(), _sync_states(), "IN_SYNC", rts)
    assert any("rtb-priv-b" in f and "0.0.0.0/0" in f for f in failures)


def test_firewall_default_wrong_nat_fails() -> None:
    rts = _route_tables()
    fw_a = next(t for t in rts if t["RouteTableId"] == "rtb-fw-a")
    for r in fw_a["Routes"]:
        if r["DestinationCidrBlock"] == "0.0.0.0/0":
            r["NatGatewayId"] = "nat-wrong"
    failures = evaluate_inspection(_contract(), _sync_states(), "IN_SYNC", rts)
    assert any("rtb-fw-a" in f for f in failures)


def test_blackhole_route_fails() -> None:
    rts = _route_tables()
    rts[1]["Routes"][1]["State"] = "blackhole"
    failures = evaluate_inspection(_contract(), _sync_states(), "IN_SYNC", rts)
    assert any("blackhole" in f for f in failures)


def test_blackhole_private_default_fails() -> None:
    rts = _route_tables()
    priv_a = next(t for t in rts if t["RouteTableId"] == "rtb-priv-a")
    for r in priv_a["Routes"]:
        if r["DestinationCidrBlock"] == "0.0.0.0/0":
            r["State"] = "blackhole"
    failures = evaluate_inspection(_contract(), _sync_states(), "IN_SYNC", rts)
    assert any("rtb-priv-a" in f and "blackhole" in f for f in failures)


def test_blackhole_firewall_default_fails() -> None:
    rts = _route_tables()
    fw_b = next(t for t in rts if t["RouteTableId"] == "rtb-fw-b")
    for r in fw_b["Routes"]:
        if r["DestinationCidrBlock"] == "0.0.0.0/0":
            r["State"] = "blackhole"
    failures = evaluate_inspection(_contract(), _sync_states(), "IN_SYNC", rts)
    assert any("rtb-fw-b" in f and "blackhole" in f for f in failures)


def test_missing_route_table_fails() -> None:
    rts = [t for t in _route_tables() if t["RouteTableId"] != "rtb-fw-b"]
    failures = evaluate_inspection(_contract(), _sync_states(), "IN_SYNC", rts)
    assert any("rtb-fw-b" in f for f in failures)


# --------------------------------------------------------------------------- #
# main — end to end with injected runners
# --------------------------------------------------------------------------- #


class _FakeAws:
    """Dispatch fake for aws_run: returns crafted describe payloads."""

    def __init__(self, sync_states: dict, summary: str, route_tables: list[dict]) -> None:
        self._describe_firewall = {
            "FirewallStatus": {
                "Status": "READY",
                "ConfigurationSyncStateSummary": summary,
                "SyncStates": sync_states,
            }
        }
        self._route_tables = {"RouteTables": route_tables}
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> dict:
        self.calls.append(args)
        if args[:2] == ["network-firewall", "describe-firewall"]:
            return self._describe_firewall
        if args[:2] == ["ec2", "describe-route-tables"]:
            return self._route_tables
        raise AssertionError(f"unexpected aws call: {args}")


def _tf_output(contract: dict):
    def _inner(_working_dir: Path) -> dict:
        return {"portal_inspection_assertion": {"value": contract, "type": "object"}}

    return _inner


def test_main_passes_with_healthy_topology() -> None:
    aws = _FakeAws(_sync_states(), "IN_SYNC", _route_tables())
    out = io.StringIO()
    rc = main(
        ["--tf-outputs-from", "."],
        aws_run=aws,
        terraform_output_json=_tf_output(_contract()),
        out_stream=out,
    )
    assert rc == 0
    assert "OK" in out.getvalue()


def test_main_noops_when_inspection_disabled() -> None:
    aws = _FakeAws(_sync_states(), "IN_SYNC", _route_tables())
    out = io.StringIO()
    rc = main(
        ["--tf-outputs-from", "."],
        aws_run=aws,
        terraform_output_json=_tf_output(_contract(enabled=False)),
        out_stream=out,
    )
    assert rc == 0
    assert aws.calls == []  # no AWS calls when inspection is off


def test_main_fails_and_emits_error_on_broken_endpoint() -> None:
    rts = _route_tables()
    rts[0]["Routes"][1]["VpcEndpointId"] = "vpce-old"
    aws = _FakeAws(_sync_states(), "IN_SYNC", rts)
    out = io.StringIO()
    rc = main(
        ["--tf-outputs-from", "."],
        aws_run=aws,
        terraform_output_json=_tf_output(_contract()),
        out_stream=out,
    )
    assert rc == 1
    assert "::error::" in out.getvalue()


def test_main_does_not_mutate_inputs() -> None:
    contract = _contract()
    snapshot = copy.deepcopy(contract)
    aws = _FakeAws(_sync_states(), "IN_SYNC", _route_tables())
    main(
        ["--tf-outputs-from", "."],
        aws_run=aws,
        terraform_output_json=_tf_output(contract),
        out_stream=io.StringIO(),
    )
    assert contract == snapshot
