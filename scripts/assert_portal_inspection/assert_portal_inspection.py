#!/usr/bin/env python3
"""Fail the portal deploy if NFW inspection wiring would blackhole egress.

The portal east-west inspection boundary (#122) puts an AWS Network Firewall
inline on the ALB->target and portal->NAT paths. When `enable_portal_inspection`
is on, `main.tf` removes the direct private->NAT default route, so every
private-tier egress flow goes private -> firewall endpoint -> NAT. The firewall
endpoint IDs are discovered at apply time from
`firewall_status.sync_states` and wired into the per-AZ route tables. If an
endpoint is stale, in the wrong AZ, unhealthy, or missing, the route silently
blackholes outbound traffic — `terraform apply` still succeeds, and the deploy
looks green while egress is dead.

This check runs after `terraform apply` in the portal apply job and proves, on
live AWS state, that:

  * the firewall configuration is IN_SYNC and every per-AZ endpoint attachment
    is READY,
  * the live `sync_states` endpoint IDs match the Terraform-declared
    `endpoint_ids_by_az`,
  * every firewall-targeted route in the public/private route tables points at
    the same-AZ healthy endpoint,
  * each private route table has a `0.0.0.0/0` default via the same-AZ firewall
    endpoint and NO direct `0.0.0.0/0 -> NAT` bypass, and
  * each firewall route table sends `0.0.0.0/0` onward to the shared NAT.

Any mismatch fails the deploy (non-zero exit + bounded `::error::` diagnostics)
instead of letting a blackhole ship. When inspection is disabled the check is a
no-op.

Usage from the workflow:

    python3 scripts/assert_portal_inspection/assert_portal_inspection.py \
        --tf-outputs-from <terraform-working-dir>

`--tf-outputs-from` runs `terraform output -json` in the given directory and
reads the single typed `portal_inspection_assertion` output. The output is
parsed in memory (never written to disk) so any sensitive Terraform outputs are
not persisted.

Exit code 0 if the wiring is healthy (or inspection is off), non-zero otherwise.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 - aws/terraform CLIs are the deploy-job interface
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

DEFAULT_ROUTE = "0.0.0.0/0"
HEALTHY_ATTACHMENT_STATUS = "READY"
IN_SYNC = "IN_SYNC"
ASSERTION_OUTPUT = "portal_inspection_assertion"

# A runner that takes an aws CLI sub-command (argv after `aws`) and returns the
# parsed JSON response. Injected in tests; defaulted to the real CLI in prod.
AwsRunFn = Callable[[list[str]], dict]
TerraformOutputFn = Callable[[Path], dict]


def load_contract(tf_outputs: Mapping[str, Any]) -> dict:
    """Extract the `portal_inspection_assertion` value from `terraform output -json`."""
    entry = tf_outputs.get(ASSERTION_OUTPUT)
    if entry is None:
        raise RuntimeError(
            f"terraform outputs do not contain {ASSERTION_OUTPUT!r}; the portal root "
            "module must expose the inspection assertion contract output."
        )
    value = entry.get("value") if isinstance(entry, Mapping) else entry
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{ASSERTION_OUTPUT!r} output is not an object: {value!r}")
    return dict(value)


def _route_endpoint(route: Mapping[str, Any]) -> str | None:
    # A route targeting a Gateway Load Balancer VPC endpoint (the Network
    # Firewall endpoint) is reported by EC2 DescribeRouteTables under
    # GatewayId as "vpce-...", not VpcEndpointId. Accept either so the
    # firewall-endpoint routes are recognized.
    endpoint = route.get("VpcEndpointId")
    if endpoint:
        return endpoint
    gateway = route.get("GatewayId")
    if isinstance(gateway, str) and gateway.startswith("vpce-"):
        return gateway
    return None


def _route_nat(route: Mapping[str, Any]) -> str | None:
    return route.get("NatGatewayId")


def _index_route_tables(route_tables: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {rt.get("RouteTableId", ""): rt for rt in route_tables}


def _check_firewall_health(
    contract: Mapping[str, Any],
    sync_states: Mapping[str, Any],
    config_sync_summary: str,
    failures: list[str],
) -> dict[str, str]:
    """Validate firewall sync + per-AZ endpoint health; return AZ -> live endpoint id."""
    if config_sync_summary != IN_SYNC:
        failures.append(f"firewall ConfigurationSyncStateSummary is {config_sync_summary!r}, expected {IN_SYNC!r}")

    azs: list[str] = list(contract.get("availability_zones", []))
    expected_by_az: Mapping[str, Any] = contract.get("endpoint_ids_by_az", {})
    live_by_az: dict[str, str] = {}

    for az in azs:
        state = sync_states.get(az)
        if not state:
            failures.append(f"AZ {az}: no firewall sync_state present (endpoint not attached)")
            continue
        attachment = state.get("Attachment", {})
        status = attachment.get("Status")
        endpoint_id = attachment.get("EndpointId")
        if status != HEALTHY_ATTACHMENT_STATUS:
            failures.append(
                f"AZ {az}: firewall endpoint {endpoint_id!r} attachment status is {status!r}, "
                f"expected {HEALTHY_ATTACHMENT_STATUS!r}"
            )
        if not endpoint_id:
            failures.append(f"AZ {az}: firewall sync_state has no endpoint id")
            continue
        expected = expected_by_az.get(az)
        if expected != endpoint_id:
            failures.append(
                f"AZ {az}: live firewall endpoint {endpoint_id!r} does not match "
                f"Terraform-declared endpoint {expected!r}"
            )
        live_by_az[az] = endpoint_id

    return live_by_az


def _check_endpoint_routes(
    rt_id: str,
    routes: Sequence[Mapping[str, Any]],
    expected_endpoint: str,
    required_cidrs: Sequence[str],
    failures: list[str],
) -> None:
    """Every endpoint-targeted route must hit `expected_endpoint`; `required_cidrs` must be present."""
    seen_cidrs: set[str] = set()
    for route in routes:
        cidr = route.get("DestinationCidrBlock")
        if not cidr:
            # Gateway VPC endpoint routes for S3 / DynamoDB also target a
            # "vpce-..." gateway, but via a managed prefix list rather than a
            # CIDR destination. They are not firewall inspection routes — skip.
            continue
        endpoint = _route_endpoint(route)
        if endpoint is None:
            continue
        seen_cidrs.add(cidr)
        if route.get("State") == "blackhole":
            failures.append(f"route table {rt_id}: route to {cidr} via {endpoint!r} is blackhole")
        if endpoint != expected_endpoint:
            failures.append(
                f"route table {rt_id}: route to {cidr} points at {endpoint!r}, "
                f"expected same-AZ firewall endpoint {expected_endpoint!r}"
            )
    for cidr in required_cidrs:
        if cidr not in seen_cidrs:
            failures.append(
                f"route table {rt_id}: missing firewall route to {cidr} (expected via {expected_endpoint!r})"
            )


def _check_private_default(
    rt_id: str,
    routes: Sequence[Mapping[str, Any]],
    expected_endpoint: str,
    failures: list[str],
) -> None:
    """Private RT default must go via the firewall endpoint, never directly to NAT."""
    default_routes = [r for r in routes if r.get("DestinationCidrBlock") == DEFAULT_ROUTE]
    if not default_routes:
        failures.append(f"route table {rt_id}: no {DEFAULT_ROUTE} default route (private egress blackholed)")
        return
    for route in default_routes:
        if _route_nat(route) is not None:
            failures.append(
                f"route table {rt_id}: {DEFAULT_ROUTE} routes directly to NAT {route.get('NatGatewayId')!r}; "
                "the direct private->NAT bypass must be removed when inspection is enabled"
            )
        if route.get("State") == "blackhole":
            failures.append(f"route table {rt_id}: {DEFAULT_ROUTE} default route is blackhole (egress dead)")
        endpoint = _route_endpoint(route)
        if endpoint != expected_endpoint:
            failures.append(
                f"route table {rt_id}: {DEFAULT_ROUTE} points at {endpoint!r}, "
                f"expected same-AZ firewall endpoint {expected_endpoint!r}"
            )


def _check_firewall_default(
    rt_id: str,
    routes: Sequence[Mapping[str, Any]],
    nat_gateway_id: str | None,
    failures: list[str],
) -> None:
    """Firewall RT default must go onward to the shared NAT gateway."""
    default_routes = [r for r in routes if r.get("DestinationCidrBlock") == DEFAULT_ROUTE]
    if not default_routes:
        failures.append(f"route table {rt_id}: no {DEFAULT_ROUTE} default route to NAT")
        return
    for route in default_routes:
        nat = _route_nat(route)
        if nat != nat_gateway_id:
            failures.append(f"route table {rt_id}: {DEFAULT_ROUTE} routes to NAT {nat!r}, expected {nat_gateway_id!r}")
        if route.get("State") == "blackhole":
            failures.append(f"route table {rt_id}: {DEFAULT_ROUTE} NAT default route is blackhole (egress dead)")


def evaluate_inspection(
    contract: Mapping[str, Any],
    sync_states: Mapping[str, Any],
    config_sync_summary: str,
    route_tables: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Return a list of human-readable failure messages. Empty list means the wiring is healthy."""
    failures: list[str] = []
    live_by_az = _check_firewall_health(contract, sync_states, config_sync_summary, failures)

    azs: list[str] = list(contract.get("availability_zones", []))
    expected_by_az: Mapping[str, Any] = contract.get("endpoint_ids_by_az", {})
    by_id = _index_route_tables(route_tables)
    public_rts: list[str] = list(contract.get("public_route_table_ids", []))
    private_rts: list[str] = list(contract.get("private_route_table_ids", []))
    firewall_rts: list[str] = list(contract.get("firewall_route_table_ids", []))
    public_cidrs: list[str] = list(contract.get("public_subnet_cidrs", []))
    private_cidrs: list[str] = list(contract.get("private_subnet_cidrs", []))
    nat_gateway_id = contract.get("nat_gateway_id")

    for i, az in enumerate(azs):
        # Prefer the live endpoint; fall back to the declared one so a missing
        # sync_state still detects stale routes rather than skipping silently.
        expected_endpoint = live_by_az.get(az) or expected_by_az.get(az)
        if not expected_endpoint:
            continue

        for rt_list, name, required in (
            (public_rts, "public", private_cidrs),
            (private_rts, "private", public_cidrs),
        ):
            if i >= len(rt_list):
                failures.append(f"AZ {az}: no {name} route table id at index {i}")
                continue
            rt_id = rt_list[i]
            rt = by_id.get(rt_id)
            if rt is None:
                failures.append(f"AZ {az}: {name} route table {rt_id} not found in live state")
                continue
            routes = rt.get("Routes", [])
            _check_endpoint_routes(rt_id, routes, expected_endpoint, required, failures)
            if name == "private":
                _check_private_default(rt_id, routes, expected_endpoint, failures)

        if i >= len(firewall_rts):
            failures.append(f"AZ {az}: no firewall route table id at index {i}")
            continue
        fw_rt_id = firewall_rts[i]
        fw_rt = by_id.get(fw_rt_id)
        if fw_rt is None:
            failures.append(f"AZ {az}: firewall route table {fw_rt_id} not found in live state")
            continue
        _check_firewall_default(fw_rt_id, fw_rt.get("Routes", []), nat_gateway_id, failures)

    return failures


def _default_aws_run(args: list[str]) -> dict:
    """Call `aws <args> --output json` and return the parsed JSON."""
    aws_bin = shutil.which("aws")
    if aws_bin is None:
        raise RuntimeError(
            "aws CLI not found on PATH; this script is intended to run inside the "
            "portal apply job where AWS credentials are already configured."
        )
    proc = subprocess.run(  # nosec B603 - args list, no shell, fixed argv
        [aws_bin, *args, "--no-cli-pager", "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"aws {' '.join(args)} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def _default_terraform_output_json(working_dir: Path) -> dict:
    """Run `terraform output -json` in `working_dir` and return the parsed dict."""
    terraform_bin = shutil.which("terraform")
    if terraform_bin is None:
        raise RuntimeError("terraform CLI not found on PATH")
    proc = subprocess.run(  # nosec B603 - args list, no shell, fixed argv
        [terraform_bin, "output", "-json"],
        capture_output=True,
        text=True,
        cwd=str(working_dir),
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"terraform output -json failed in {working_dir}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def run_assertion(contract: Mapping[str, Any], aws_run: AwsRunFn, out_stream: TextIO) -> int:
    """Run the live-state assertion for a loaded contract. Returns the exit code."""
    if not contract.get("inspection_enabled"):
        out_stream.write("OK    portal inspection is disabled; no route/endpoint wiring to assert\n")
        return 0

    firewall_arn = contract.get("firewall_arn")
    if not firewall_arn:
        out_stream.write("::error::portal inspection is enabled but firewall_arn output is empty\n")
        return 1

    describe = aws_run(["network-firewall", "describe-firewall", "--firewall-arn", firewall_arn])
    status = describe.get("FirewallStatus", {})
    sync_states = status.get("SyncStates", {})
    summary = status.get("ConfigurationSyncStateSummary", "")

    rt_ids = [
        *contract.get("public_route_table_ids", []),
        *contract.get("private_route_table_ids", []),
        *contract.get("firewall_route_table_ids", []),
    ]
    route_tables: list[Mapping[str, Any]] = []
    if rt_ids:
        described = aws_run(["ec2", "describe-route-tables", "--route-table-ids", *rt_ids])
        route_tables = described.get("RouteTables", [])

    failures = evaluate_inspection(contract, sync_states, summary, route_tables)
    if failures:
        out_stream.write(
            f"::error::portal inspection wiring assertion failed ({len(failures)} problem(s)); "
            "the deploy would blackhole egress and is rejected\n"
        )
        for failure in failures:
            out_stream.write(f"::error::{failure}\n")
        return 1

    out_stream.write(
        f"OK    portal inspection wiring healthy across {len(contract.get('availability_zones', []))} AZ(s)\n"
    )
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    aws_run: AwsRunFn = _default_aws_run,
    terraform_output_json: TerraformOutputFn = _default_terraform_output_json,
    out_stream: TextIO = sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(
        description="Fail the deploy if portal NFW inspection route/endpoint wiring is unhealthy.",
    )
    parser.add_argument(
        "--tf-outputs-from",
        type=Path,
        default=Path("."),
        help=f"Terraform working directory; runs `terraform output -json` and reads the {ASSERTION_OUTPUT!r} output.",
    )
    args = parser.parse_args(argv)

    tf_outputs = terraform_output_json(args.tf_outputs_from)
    contract = load_contract(tf_outputs)
    return run_assertion(contract, aws_run, out_stream)


if __name__ == "__main__":
    sys.exit(main())
