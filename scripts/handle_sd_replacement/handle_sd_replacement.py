#!/usr/bin/env python3
"""Drain ECS services from Cloud Map before a Service Discovery ForceNew apply, then restore.

When ``aws_service_discovery_service`` has a ForceNew attribute (e.g.
``health_check_custom_config.failure_threshold``), Terraform must delete the
existing service-discovery record and create a new one. If ECS tasks are still
registered in Cloud Map at delete time, the apply fails. This script handles
the two sides of that window:

``drain``
    Reads the saved Terraform plan, detects ``aws_service_discovery_service``
    resources with a delete action, scales each mapped ECS service to
    ``desiredCount=0``, waits for Cloud Map to deregister all instances, and
    writes a snapshot of the original desired counts.  If no SD deletion is
    detected, writes an empty snapshot and exits 0.

``restore``
    Reads the snapshot and restores each service to its original desired count.
    Idempotent: no-op when the snapshot is missing or empty.

Usage from the workflow (job default working-directory is the Terraform portal
environment directory):

    # Before terraform apply
    python3 "${GITHUB_WORKSPACE}/scripts/handle_sd_replacement/handle_sd_replacement.py" \\
        drain --tf-plan tfplan --tf-outputs-from .

    # After terraform apply
    python3 "${GITHUB_WORKSPACE}/scripts/handle_sd_replacement/handle_sd_replacement.py" \\
        restore --snapshot sd_replacement_snapshot.json

Exit code 0 on success, 1 on any failure or timeout.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 - aws/terraform CLIs are the deploy-job interface
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

TerraformShowFn = Callable[[str], dict]
TerraformOutputsFn = Callable[[Path], dict]
AwsEcsDescribeFn = Callable[[str, str], dict]
AwsEcsUpdateFn = Callable[[str, str, int], None]
AwsSdListFn = Callable[[str], dict]
SleepFn = Callable[[float], None]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_ATTEMPTS = 24  # 24 x 5 s = 2 min -- fits the CI drain window
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_SD_MAX_ATTEMPTS = 12  # 12 x 5 s = 1 min for Cloud Map propagation
DEFAULT_SD_POLL_INTERVAL = 5.0

SNAPSHOT_FILENAME = "sd_replacement_snapshot.json"

# Centralised mapping: SD resource address suffix -> terraform output key for
# the corresponding ECS service name.  The suffix is the last dotted segment
# of the Terraform resource address (e.g. "guacd" from
# "module.guacamole.aws_service_discovery_service.guacd").  Add a new entry
# here when a new SD service is introduced.
_SD_SUFFIX_TO_OUTPUT_KEY: dict[str, str] = {
    "guacd": "guacd_service_name",
    "guacamole_client": "guacamole_client_service_name",
}

_CLUSTER_OUTPUT_KEY = "guacamole_ecs_cluster_name"

# ---------------------------------------------------------------------------
# Default subprocess-based runners (no boto3; mirrors check_rds pattern)
# ---------------------------------------------------------------------------


def _default_terraform_show(tf_plan: str) -> dict:
    """Run ``terraform show -json <tfplan>`` and return the parsed JSON."""
    terraform_bin = shutil.which("terraform")
    if terraform_bin is None:
        raise RuntimeError("terraform CLI not found on PATH; this script runs inside the deploy job.")
    proc = subprocess.run(  # nosec B603 - args list, no shell, fixed argv
        [terraform_bin, "show", "-json", tf_plan],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"terraform show -json {tf_plan!r} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def _default_terraform_outputs(working_dir: Path) -> dict:
    """Run ``terraform output -json`` in ``working_dir`` and return the parsed dict.

    Output is held in memory and never written to disk: the payload may
    include sensitive outputs, and we only need specific non-secret keys.
    """
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


def _default_ecs_describe(cluster: str, service: str) -> dict:
    """Call ``aws ecs describe-services`` and return the parsed JSON."""
    aws_bin = shutil.which("aws")
    if aws_bin is None:
        raise RuntimeError("aws CLI not found on PATH")
    proc = subprocess.run(  # nosec B603 - args list, no shell, fixed argv
        [
            aws_bin,
            "ecs",
            "describe-services",
            "--cluster",
            cluster,
            "--services",
            service,
            "--no-cli-pager",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aws ecs describe-services failed for {service!r} in cluster {cluster!r}: {proc.stderr.strip()}"
        )
    return json.loads(proc.stdout)


def _default_ecs_update(cluster: str, service: str, desired_count: int) -> None:
    """Call ``aws ecs update-service --desired-count``."""
    aws_bin = shutil.which("aws")
    if aws_bin is None:
        raise RuntimeError("aws CLI not found on PATH")
    proc = subprocess.run(  # nosec B603 - args list, no shell, fixed argv
        [
            aws_bin,
            "ecs",
            "update-service",
            "--cluster",
            cluster,
            "--service",
            service,
            "--desired-count",
            str(desired_count),
            "--no-cli-pager",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aws ecs update-service failed for {service!r} desired-count={desired_count}: {proc.stderr.strip()}"
        )


def _default_sd_list(service_id: str) -> dict:
    """Call ``aws servicediscovery list-instances`` and return the parsed JSON."""
    aws_bin = shutil.which("aws")
    if aws_bin is None:
        raise RuntimeError("aws CLI not found on PATH")
    proc = subprocess.run(  # nosec B603 - args list, no shell, fixed argv
        [
            aws_bin,
            "servicediscovery",
            "list-instances",
            "--service-id",
            service_id,
            "--no-cli-pager",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"aws servicediscovery list-instances failed for {service_id!r}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# Core logic helpers
# ---------------------------------------------------------------------------


def _extract_value(tf_outputs: dict, key: str) -> str:
    """Extract a string value from a parsed ``terraform output -json`` payload."""
    entry = tf_outputs.get(key)
    if entry is None:
        raise KeyError(f"terraform output key {key!r} not found in outputs")
    raw = entry.get("value") if isinstance(entry, dict) else entry
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"terraform output key {key!r} has empty or non-string value: {raw!r}")
    return raw


def _detect_sd_deletions(plan_json: dict) -> list[dict]:
    """Return resource_changes entries for aws_service_discovery_service with a delete action.

    Raises ValueError if the plan payload is missing the ``resource_changes``
    key -- that indicates a caller error (wrong file or non-plan JSON).
    """
    resource_changes = plan_json.get("resource_changes")
    if resource_changes is None:
        raise ValueError("plan JSON missing 'resource_changes' key -- is this a valid ``terraform show -json`` output?")
    results = []
    for change in resource_changes:
        if change.get("type") != "aws_service_discovery_service":
            continue
        actions = change.get("change", {}).get("actions") or []
        if "delete" in actions:
            results.append(change)
    return results


def _address_suffix(address: str) -> str:
    """Return the last dotted segment of a Terraform resource address.

    ``module.guacamole.aws_service_discovery_service.guacd`` -> ``"guacd"``
    """
    return address.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DrainDeps:
    """Injected AWS runners and bounded-poll tuning for the drain path.

    Bundled into one object so the per-service helpers keep small signatures
    while ``drain`` stays under the McCabe complexity gate (ADR-012).
    """

    ecs_describe: AwsEcsDescribeFn
    ecs_update: AwsEcsUpdateFn
    sd_list: AwsSdListFn
    sleep: SleepFn
    max_attempts: int
    poll_interval: float
    sd_max_attempts: int
    sd_poll_interval: float


def _wait_for_ecs_drain(
    cluster: str,
    service_name: str,
    deps: _DrainDeps,
    out_stream: TextIO,
) -> bool:
    """Poll ECS until ``runningCount`` reaches 0. Return True on success, False on error/timeout."""
    for attempt in range(max(1, deps.max_attempts)):
        try:
            poll_resp = deps.ecs_describe(cluster, service_name)
        except Exception as exc:
            out_stream.write(
                f"::error::Poll describe failed service={service_name!r} "
                f"cluster={cluster!r} attempt={attempt + 1}: {exc}\n"
            )
            return False
        running = (poll_resp.get("services") or [{}])[0].get("runningCount", 0)
        out_stream.write(
            f"  runningCount={running} service={service_name!r} (attempt {attempt + 1}/{deps.max_attempts})\n"
        )
        if running == 0:
            out_stream.write(f"  All tasks stopped for {service_name!r}\n")
            return True
        if attempt == max(1, deps.max_attempts) - 1:
            out_stream.write(
                f"::error::Timeout waiting for service={service_name!r} "
                f"cluster={cluster!r} to drain; runningCount={running} "
                f"after {deps.max_attempts} attempts\n"
            )
            return False
        deps.sleep(deps.poll_interval)
    return False


def _wait_for_cloud_map_deregister(
    sd_service_id: str,
    cluster: str,
    service_name: str,
    address: str,
    deps: _DrainDeps,
    out_stream: TextIO,
) -> bool:
    """Poll Cloud Map until zero registered instances. Return True on success, False on error/timeout."""
    for attempt in range(max(1, deps.sd_max_attempts)):
        try:
            instances_resp = deps.sd_list(sd_service_id)
        except Exception as exc:
            out_stream.write(
                f"::error::Cloud Map list-instances failed "
                f"service_id={sd_service_id!r} address={address!r} "
                f"attempt={attempt + 1}: {exc}\n"
            )
            return False
        instances = instances_resp.get("Instances") or []
        count = len(instances)
        out_stream.write(
            f"  Cloud Map instances={count} service_id={sd_service_id!r} "
            f"(attempt {attempt + 1}/{deps.sd_max_attempts})\n"
        )
        if count == 0:
            out_stream.write(f"  Cloud Map deregistered for service_id={sd_service_id!r}\n")
            return True
        if attempt == max(1, deps.sd_max_attempts) - 1:
            out_stream.write(
                f"::error::Timeout waiting for Cloud Map to deregister; "
                f"service_id={sd_service_id!r} cluster={cluster!r} "
                f"service={service_name!r} address={address!r} "
                f"instances={count} after {deps.sd_max_attempts} attempts\n"
            )
            return False
        deps.sleep(deps.sd_poll_interval)
    return False


def _write_snapshot(snapshot_path: Path, snapshot: dict[str, int | str]) -> None:
    """Persist the restore snapshot to disk.

    Called incrementally during drain so the restore input is durable BEFORE
    any out-of-band scale-down, not only after every service drains. A drain
    timeout, Cloud Map polling failure, or failed ``terraform apply`` after a
    scale-down must still leave a snapshot the restore step can act on.
    """
    snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")


def _drain_one_service(
    change: dict,
    cluster: str,
    tf_out: dict,
    deps: _DrainDeps,
    snapshot: dict[str, int | str],
    snapshot_path: Path,
    out_stream: TextIO,
) -> bool:
    """Scale one SD-backed ECS service to 0 and wait for it to deregister.

    Records the original desired count in ``snapshot`` and persists the
    snapshot to disk before scaling, so the restore path is durable even if a
    later step in this drain (or the subsequent apply) fails. Returns True on
    success, False on any failure or timeout (the error is already logged).
    """
    address = change.get("address", "<unknown>")
    suffix = _address_suffix(address)
    output_key = _SD_SUFFIX_TO_OUTPUT_KEY.get(suffix)
    if output_key is None:
        out_stream.write(
            f"::error::No ECS service mapping for SD address suffix {suffix!r} "
            f"(address={address!r}); add it to _SD_SUFFIX_TO_OUTPUT_KEY\n"
        )
        return False

    try:
        service_name = _extract_value(tf_out, output_key)
    except (KeyError, ValueError) as exc:
        out_stream.write(f"::error::Cannot determine ECS service name for address={address!r}: {exc}\n")
        return False

    # Extract the Cloud Map service ID from the plan's before-state.
    before = change.get("change", {}).get("before") or {}
    raw_id = before.get("id")
    sd_service_id = str(raw_id) if raw_id else None

    # Describe ECS service to verify it exists and capture desiredCount.
    try:
        describe_resp = deps.ecs_describe(cluster, service_name)
    except Exception as exc:
        out_stream.write(
            f"::error::Failed to describe ECS service={service_name!r} cluster={cluster!r} address={address!r}: {exc}\n"
        )
        return False

    services = describe_resp.get("services") or []
    if not services or services[0].get("status") != "ACTIVE":
        out_stream.write(
            f"::error::ECS service {service_name!r} not found or not ACTIVE "
            f"in cluster {cluster!r} (address={address!r})\n"
        )
        return False

    original_desired = services[0].get("desiredCount", 0)
    out_stream.write(
        f"Draining: address={address!r} cluster={cluster!r} service={service_name!r} desiredCount={original_desired}\n"
    )
    snapshot[service_name] = original_desired
    # Persist BEFORE the out-of-band scale-down so a later failure (drain
    # timeout, Cloud Map poll error, or failed apply) still has a restore input.
    _write_snapshot(snapshot_path, snapshot)

    # Scale ECS service to 0.
    try:
        deps.ecs_update(cluster, service_name, 0)
    except Exception as exc:
        out_stream.write(f"::error::Failed to scale service={service_name!r} cluster={cluster!r} to 0: {exc}\n")
        return False

    if not _wait_for_ecs_drain(cluster, service_name, deps, out_stream):
        return False

    # No Cloud Map service ID in the plan means nothing to deregister: success.
    if not sd_service_id:
        return True
    return _wait_for_cloud_map_deregister(sd_service_id, cluster, service_name, address, deps, out_stream)


def drain(
    tf_plan: str,
    tf_outputs_from: Path,
    terraform_show: TerraformShowFn = _default_terraform_show,
    terraform_outputs: TerraformOutputsFn = _default_terraform_outputs,
    ecs_describe: AwsEcsDescribeFn = _default_ecs_describe,
    ecs_update: AwsEcsUpdateFn = _default_ecs_update,
    sd_list: AwsSdListFn = _default_sd_list,
    sleep: SleepFn = time.sleep,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    sd_max_attempts: int = DEFAULT_SD_MAX_ATTEMPTS,
    sd_poll_interval: float = DEFAULT_SD_POLL_INTERVAL,
    out_stream: TextIO = sys.stdout,
    snapshot_path: Path = Path(SNAPSHOT_FILENAME),
) -> int:
    """Scale ECS services to 0 for each SD service about to be deleted, then write snapshot.

    Returns 0 on success, 1 on any failure or timeout.
    """
    try:
        plan_json = terraform_show(tf_plan)
    except Exception as exc:
        out_stream.write(f"::error::Failed to read terraform plan {tf_plan!r}: {exc}\n")
        return 1

    try:
        deletions = _detect_sd_deletions(plan_json)
    except ValueError as exc:
        out_stream.write(f"::error::Malformed plan JSON: {exc}\n")
        return 1

    if not deletions:
        out_stream.write("No aws_service_discovery_service deletion detected in plan -- no drain needed.\n")
        snapshot_path.write_text(json.dumps({}), encoding="utf-8")
        return 0

    # Load TF outputs once (kept in memory only; may include sensitive values).
    try:
        tf_out = terraform_outputs(tf_outputs_from)
    except Exception as exc:
        out_stream.write(f"::error::Failed to read terraform outputs: {exc}\n")
        return 1

    try:
        cluster = _extract_value(tf_out, _CLUSTER_OUTPUT_KEY)
    except (KeyError, ValueError) as exc:
        out_stream.write(f"::error::Cannot determine ECS cluster name: {exc}\n")
        return 1

    deps = _DrainDeps(
        ecs_describe=ecs_describe,
        ecs_update=ecs_update,
        sd_list=sd_list,
        sleep=sleep,
        max_attempts=max_attempts,
        poll_interval=poll_interval,
        sd_max_attempts=sd_max_attempts,
        sd_poll_interval=sd_poll_interval,
    )

    # Write the cluster-only snapshot up front so restore always has the
    # cluster, then each service is appended durably before it is scaled down.
    snapshot: dict[str, int | str] = {"cluster": cluster}
    _write_snapshot(snapshot_path, snapshot)
    for change in deletions:
        if not _drain_one_service(change, cluster, tf_out, deps, snapshot, snapshot_path, out_stream):
            return 1

    _write_snapshot(snapshot_path, snapshot)
    out_stream.write(f"Snapshot written to {snapshot_path}\n")
    return 0


def restore(
    snapshot_path: Path,
    ecs_update: AwsEcsUpdateFn = _default_ecs_update,
    out_stream: TextIO = sys.stdout,
) -> int:
    """Restore ECS desired counts from snapshot.

    Idempotent: exits 0 without calling AWS when the snapshot is missing or empty.
    """
    if not snapshot_path.exists():
        out_stream.write(f"No snapshot at {snapshot_path} -- nothing to restore.\n")
        return 0

    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception as exc:
        out_stream.write(f"::error::Failed to read snapshot {snapshot_path}: {exc}\n")
        return 1

    if not snapshot:
        out_stream.write("Empty snapshot -- nothing to restore.\n")
        return 0

    cluster = snapshot.get("cluster")
    if not cluster:
        out_stream.write("::error::Snapshot missing 'cluster' key.\n")
        return 1

    for key, value in snapshot.items():
        if key == "cluster":
            continue
        service_name = key
        desired_count = int(value)
        out_stream.write(f"Restoring: cluster={cluster!r} service={service_name!r} desiredCount={desired_count}\n")
        try:
            ecs_update(cluster, service_name, desired_count)
        except Exception as exc:
            out_stream.write(
                f"::error::Failed to restore service={service_name!r} "
                f"cluster={cluster!r} to desiredCount={desired_count}: {exc}\n"
            )
            return 1

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_argv_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Drain/restore ECS services around a Service Discovery ForceNew apply. "
            "Run 'drain' before terraform apply and 'restore' after."
        ),
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    drain_p = subparsers.add_parser(
        "drain",
        help="Scale ECS services to 0 before terraform apply",
    )
    drain_p.add_argument(
        "--tf-plan",
        required=True,
        help="Path to the saved terraform plan file (e.g. tfplan)",
    )
    drain_p.add_argument(
        "--tf-outputs-from",
        type=Path,
        required=True,
        help="Terraform working directory; runs `terraform output -json` there",
    )

    restore_p = subparsers.add_parser(
        "restore",
        help="Restore ECS desired counts after terraform apply",
    )
    restore_p.add_argument(
        "--snapshot",
        type=Path,
        required=True,
        help="Path to the snapshot JSON written by the drain subcommand",
    )

    return parser


def _entry() -> int:
    parser = _build_argv_parser()
    args = parser.parse_args()

    if args.subcommand == "drain":
        return drain(
            tf_plan=args.tf_plan,
            tf_outputs_from=args.tf_outputs_from,
        )
    if args.subcommand == "restore":
        return restore(snapshot_path=args.snapshot)
    # subparsers(required=True) prevents reaching here.
    print(f"Unknown subcommand: {args.subcommand}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_entry())
