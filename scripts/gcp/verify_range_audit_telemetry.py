#!/usr/bin/env python3
"""Read-only deployment readback of the GCP range audit telemetry controls (#2535).

Compares the applied state with ``settings.range_telemetry`` in ``shifter.yaml`` and
reports each control on its own line:

* ``vertex_data_access_logs``: the platform project audit config for
  ``aiplatform.googleapis.com`` (or ``allServices``) carries ``DATA_READ`` and
  ``DATA_WRITE`` with no exempted members;
* ``vpc_flow_logs``: every subnetwork in the range placement has the configured flow-log
  settings;
* ``nat_logs``: every Cloud NAT gateway in the range placement has the configured filter.

The range placement is the Terraform range VPC plus every provisioner per-range VPC
(``shifter-range-<id>``) in the platform project and the range-cell project. Resources
fall into two owners:

* Terraform-owned resources (named by the caller from Terraform outputs) converge in the
  same deploy, so a mismatch, or a missing Terraform-owned resource, is ``FAIL``.
* Provisioner-owned range resources converge only when a range is provisioned again with
  the deployed runtime policy, so a mismatch is ``DRIFT``: reported as pending
  reprovision, not a deploy failure.

Other status values: ``PASS``, ``DISABLED`` (the operator turned the control off; a
coverage warning), and ``NOT_APPLICABLE`` (no resources in the range placement yet). A
failed readback is ``FAIL``, never an empty deployment. The script exits non-zero when
any control fails. Output names controls, settings, counts, and range resource names only,
never provider payloads, principals, or command output. Project-level audit configuration
is read; folder or organization inheritance is outside this check.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess  # nosec B404 - required CLI adapter; calls below use argv without a shell.
import sys
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass

from installation.errors import InstallationConfigError
from installation.loader import load_root_config
from installation.settings_gcp import GcpBackendSettings
from shared.gcp_range_telemetry import GcpRangeTelemetryPolicy, NatLogPolicy, VpcFlowLogPolicy

_VERTEX_SERVICE = "aiplatform.googleapis.com"
_DATA_LOG_TYPES = frozenset({"DATA_READ", "DATA_WRITE"})
# The provisioner names a vpc-per-range network ``shifter-range-<range id>``
# (``_short_resource_name("shifter-range", range_id)`` in the GCE plan builders).
_PER_RANGE_NETWORK = re.compile(r"^shifter-range-\d+$")
_MAX_LISTED = 10
_TIMEOUT_SECONDS = 120

Runner = Callable[..., object]


@dataclass(frozen=True)
class ControlResult:
    """The readback outcome for one telemetry control."""

    control: str
    status: str
    desired: str
    observed: str
    checked: int = 0
    mismatched: tuple[str, ...] = ()
    pending_reprovision: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Resource:
    """One subnet or NAT gateway in the range placement."""

    name: str
    log_config: Mapping[str, object]
    terraform_owned: bool


def _gcloud(*args: str) -> object:
    """Run one fixed read-only gcloud command and parse its JSON output."""
    result = subprocess.run(  # nosec B603 B607 - fixed CLI from the operator/CI toolchain.
        ["gcloud", *args, "--format=json", "--quiet"],
        capture_output=True,
        text=True,
        check=True,
        timeout=_TIMEOUT_SECONDS,
    )
    return json.loads(result.stdout or "null")


def _read(run: Runner, *args: str) -> object | None:
    """Return a readback payload, or None when the readback fails for any reason."""
    try:
        return run(*args)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _mapping_items(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _network_name(resource: Mapping[str, object]) -> str:
    return str(resource.get("network", "")).rstrip("/").rsplit("/", 1)[-1]


def _log_config(resource: Mapping[str, object]) -> Mapping[str, object]:
    value = resource.get("logConfig")
    return value if isinstance(value, Mapping) else {}


def _list_projects(run: Runner, projects: Iterable[str], *command: str) -> list[Mapping[str, object]] | None:
    """List one resource kind in every project; None when any project is unreadable."""
    items: list[Mapping[str, object]] = []
    for project in projects:
        payload = _read(run, *command, "--project", project)
        if not isinstance(payload, list):
            return None
        items.extend(_mapping_items(payload))
    return items


def _verify_vertex(policy: GcpRangeTelemetryPolicy, project_id: str, run: Runner) -> ControlResult:
    control = "vertex_data_access_logs"
    desired = "DATA_READ+DATA_WRITE" if policy.vertex_data_access_logs.enabled else "disabled"
    iam_policy = _read(run, "projects", "get-iam-policy", project_id)
    if not isinstance(iam_policy, Mapping):
        return ControlResult(control, "FAIL", desired, "readback-failed")
    log_types: set[str] = set()
    exempted = False
    for audit in _mapping_items(iam_policy.get("auditConfigs")):
        if audit.get("service") not in {_VERTEX_SERVICE, "allServices"}:
            continue
        for entry in _mapping_items(audit.get("auditLogConfigs")):
            log_type = str(entry.get("logType", ""))
            log_types.add(log_type)
            if log_type in _DATA_LOG_TYPES and entry.get("exemptedMembers"):
                exempted = True
    present = sorted(log_types & _DATA_LOG_TYPES)
    observed = "+".join(present) or "none"
    if exempted:
        observed += " exempted-members"
    if not policy.vertex_data_access_logs.enabled:
        return ControlResult(control, "DISABLED", desired, observed)
    status = "PASS" if set(present) == _DATA_LOG_TYPES and not exempted else "FAIL"
    return ControlResult(control, status, desired, observed)


def _flow_matches(log_config: Mapping[str, object], flow: VpcFlowLogPolicy) -> bool:
    sampling = log_config.get("flowSampling")
    return (
        log_config.get("enable") is True
        and log_config.get("aggregationInterval") == flow.aggregation_interval.value
        and isinstance(sampling, int | float)
        and math.isclose(float(sampling), flow.flow_sampling, rel_tol=1e-6)
        and log_config.get("metadata") == flow.metadata.value
    )


def _nat_matches(log_config: Mapping[str, object], nat: NatLogPolicy) -> bool:
    return log_config.get("enable") is True and log_config.get("filter") == nat.filter.value


def _resource_result(
    control: str,
    enabled: bool,
    desired: str,
    resources: list[_Resource] | None,
    missing_terraform: Collection[str],
    matches: Callable[[Mapping[str, object]], bool],
) -> ControlResult:
    if resources is None:
        return ControlResult(control, "FAIL", desired, "readback-failed")
    logging = sum(1 for resource in resources if resource.log_config.get("enable") is True)
    observed = f"{logging}/{len(resources)} logging"
    if not enabled:
        return ControlResult(control, "DISABLED", desired, observed, checked=len(resources))
    if not resources and not missing_terraform:
        return ControlResult(control, "NOT_APPLICABLE", desired, "no range resources yet")
    drifted = [resource for resource in resources if not matches(resource.log_config)]
    mismatched = tuple(
        sorted([r.name for r in drifted if r.terraform_owned] + [f"{name} (missing)" for name in missing_terraform])
    )
    pending = tuple(sorted(r.name for r in drifted if not r.terraform_owned))
    status = "FAIL" if mismatched else ("DRIFT" if pending else "PASS")
    return ControlResult(
        control, status, desired, observed, checked=len(resources), mismatched=mismatched, pending_reprovision=pending
    )


def _in_placement(resource: Mapping[str, object], range_network: str) -> bool:
    network = _network_name(resource)
    return network == range_network or bool(_PER_RANGE_NETWORK.fullmatch(network))


def _verify_flow(
    policy: GcpRangeTelemetryPolicy,
    projects: Iterable[str],
    range_network: str,
    terraform_subnetworks: Collection[str],
    run: Runner,
) -> ControlResult:
    flow = policy.vpc_flow_logs
    desired = (
        f"{flow.aggregation_interval.value},{flow.flow_sampling},{flow.metadata.value}" if flow.enabled else "disabled"
    )
    subnets = _list_projects(run, projects, "compute", "networks", "subnets", "list")
    resources = (
        None
        if subnets is None
        else [
            _Resource(
                name=str(subnet.get("name", "")),
                log_config=_log_config(subnet),
                terraform_owned=_network_name(subnet) == range_network and subnet.get("name") in terraform_subnetworks,
            )
            for subnet in subnets
            if _in_placement(subnet, range_network)
        ]
    )
    seen = {resource.name for resource in resources or () if resource.terraform_owned}
    missing = sorted(set(terraform_subnetworks) - seen) if resources is not None else []
    return _resource_result(
        "vpc_flow_logs", flow.enabled, desired, resources, missing, lambda config: _flow_matches(config, flow)
    )


def _verify_nat(
    policy: GcpRangeTelemetryPolicy,
    projects: Iterable[str],
    range_network: str,
    terraform_nat_routers: Collection[str],
    run: Runner,
) -> ControlResult:
    nat = policy.nat_logs
    desired = nat.filter.value if nat.enabled else "disabled"
    routers = _list_projects(run, projects, "compute", "routers", "list")
    resources = (
        None
        if routers is None
        else [
            _Resource(
                name=f"{router.get('name', '')}/{gateway.get('name', '')}",
                log_config=_log_config(gateway),
                terraform_owned=_network_name(router) == range_network and router.get("name") in terraform_nat_routers,
            )
            for router in routers
            if _in_placement(router, range_network)
            for gateway in _mapping_items(router.get("nats"))
        ]
    )
    seen = {resource.name.split("/", 1)[0] for resource in resources or () if resource.terraform_owned}
    missing = sorted(set(terraform_nat_routers) - seen) if resources is not None else []
    return _resource_result(
        "nat_logs", nat.enabled, desired, resources, missing, lambda config: _nat_matches(config, nat)
    )


def verify(
    policy: GcpRangeTelemetryPolicy,
    *,
    project_id: str,
    range_project_id: str,
    range_network: str,
    terraform_subnetworks: Collection[str],
    terraform_nat_routers: Collection[str],
    run: Runner = _gcloud,
) -> list[ControlResult]:
    """Read back all three controls and compare them with ``policy``."""
    projects = list(dict.fromkeys([project_id, range_project_id]))
    return [
        _verify_vertex(policy, project_id, run),
        _verify_flow(policy, projects, range_network, terraform_subnetworks, run),
        _verify_nat(policy, projects, range_network, terraform_nat_routers, run),
    ]


def _listed(values: tuple[str, ...]) -> str:
    extra = len(values) - _MAX_LISTED
    return ",".join(values[:_MAX_LISTED]) + (f" (+{extra} more)" if extra > 0 else "")


def report(results: Iterable[ControlResult]) -> None:
    """Print one sanitized status line per control."""
    for result in results:
        line = (
            f"{result.control}: status={result.status} desired={result.desired} "
            f"observed={result.observed} checked={result.checked}"
        )
        if result.mismatched:
            line += f" mismatched={_listed(result.mismatched)}"
        if result.pending_reprovision:
            line += f" pending_reprovision={_listed(result.pending_reprovision)}"
        print(line)


def exit_code(results: Iterable[ControlResult]) -> int:
    """Fail when any control failed; drift, disabled, and not-applicable do not fail."""
    return 1 if any(result.status == "FAIL" for result in results) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, help="Path to shifter.yaml")
    parser.add_argument("--project-id", required=True, help="Platform project (range VPC and Vertex target)")
    parser.add_argument(
        "--range-project-id", default="", help="Range-cell project (GCP_RANGE_CELL_PROJECT_ID); default: --project-id"
    )
    parser.add_argument("--range-network", required=True, help="Name of the Terraform range VPC network")
    parser.add_argument(
        "--terraform-subnetwork", action="append", default=[], help="Terraform-owned range subnet name (repeatable)"
    )
    parser.add_argument(
        "--terraform-nat-router", action="append", default=[], help="Terraform-owned range NAT router name (repeatable)"
    )
    args = parser.parse_args(argv)
    config = load_root_config(args.config)
    policy = GcpBackendSettings.from_root_settings(config.settings).range_telemetry
    results = verify(
        policy,
        project_id=args.project_id,
        range_project_id=args.range_project_id or args.project_id,
        range_network=args.range_network,
        terraform_subnetworks=tuple(args.terraform_subnetwork),
        terraform_nat_routers=tuple(args.terraform_nat_router),
        run=_gcloud,
    )
    report(results)
    return exit_code(results)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallationConfigError:
        sys.stderr.write("shifter.yaml is invalid; range audit telemetry was not verified\n")
        raise SystemExit(1) from None
