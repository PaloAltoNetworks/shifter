#!/usr/bin/env python3
"""Fail noisily if any RDS instance has unapplied pending modifications.

After a Terraform apply, the AWS API will accept changes such as
`instance_class`, `allocated_storage`, `engine_version`, or parameter-group
membership but defer them into `PendingModifiedValues` if the underlying
deploy did not request immediate application. The May 2026 Polaris guacamole
flakiness was caused by exactly that — the `db.t3.small → db.m5.xlarge` bump
was accepted by `terraform apply` and then queued for the maintenance window,
so the live database stayed at the old class while the ops team believed the
fix had landed.

This check runs after `terraform apply` in the deploy job and fails the run
if any of the named RDS instances still have non-empty `PendingModifiedValues`
after the modify operation has had a reasonable chance to complete. A
successful apply that leaves pending mods is an incomplete deploy.

The `terraform apply` call returns when AWS *accepts* `ModifyDBInstance` —
not when RDS reaches its final state. With `apply_immediately = true`, RDS
typically transitions through `modifying` for some minutes while the change
is being applied, with `PendingModifiedValues` still populated. We therefore
poll: while `DBInstanceStatus` is non-terminal and pending values are present,
wait. Once status is `available` the verdict is final — empty pending is a
pass, non-empty pending is a fail (queued for maintenance window, or AWS is
not accepting the change). We bound the poll so a stuck modify cannot hang CI.

Usage from the workflow:

    python3 scripts/check_rds_pending_modifications/check_rds_pending_modifications.py \
        --tf-outputs-from <terraform-working-dir>

    python3 scripts/check_rds_pending_modifications/check_rds_pending_modifications.py \
        <db-instance-id> [<db-instance-id> ...]

`--tf-outputs-from` runs `terraform output -json` in the given directory and
extracts every output whose key ends with `db_instance_id`. Output is parsed
in memory (it is not written to disk) so other Terraform output values, which
may be marked sensitive, are not persisted alongside the IDs we actually use.

Exit code 0 if every instance is clean, non-zero otherwise.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 - aws CLI is the deploy-job interface
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, TextIO


@dataclass(frozen=True)
class InstanceCheck:
    """Result of checking one RDS instance for pending modifications."""

    instance_id: str
    pending: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def is_clean(self) -> bool:
        return self.error is None and not self.pending


AwsDescribeFn = Callable[[str], dict]
SleepFn = Callable[[float], None]

# Fields in `PendingModifiedValues` whose VALUES carry secrets and must not be
# echoed into CI logs. The presence of these keys is still useful signal — the
# operator needs to know a master-password rotation is queued — so we report
# the key but redact the value.
_SECRET_PENDING_FIELDS = frozenset({"MasterUserPassword"})

# DBInstanceStatus values that indicate AWS is still moving the instance to
# its target state. While the status is one of these AND pending values are
# present, we keep waiting; we do not fail. Sourced from the RDS DB Instance
# Lifecycle docs. We intentionally treat unknown statuses as terminal — if AWS
# adds a new transitional status we will surface it as a failure rather than
# poll forever.
_TRANSITIONAL_STATUSES = frozenset(
    {
        "creating",
        "modifying",
        "rebooting",
        "backing-up",
        "upgrading",
        "configuring-enhanced-monitoring",
        "configuring-iam-database-auth",
        "configuring-log-exports",
        "renaming",
        "resetting-master-credentials",
        "starting",
        "storage-optimization",
        "maintenance",
    }
)

DEFAULT_MAX_ATTEMPTS = 20  # 20 × 30 s = 10 min — fits well under the CI cap.
DEFAULT_POLL_INTERVAL = 30.0


def _default_aws_describe(instance_id: str) -> dict:
    """Call `aws rds describe-db-instances` and return the parsed JSON.

    The AWS CLI is the contract used elsewhere in `_shifter-platform.yml`
    (e.g. `aws ecs describe-services`); we keep that consistency so the
    self-hosted runner does not need an additional Python AWS SDK install.
    """
    aws_bin = shutil.which("aws")
    if aws_bin is None:
        raise RuntimeError(
            "aws CLI not found on PATH; this script is intended to run inside "
            "the Terraform deploy job where AWS credentials are already configured."
        )
    proc = subprocess.run(  # nosec B603 - args list, no shell, fixed argv
        [
            aws_bin,
            "rds",
            "describe-db-instances",
            "--db-instance-identifier",
            instance_id,
            "--no-cli-pager",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        if "DBInstanceNotFound" in proc.stderr:
            return {"DBInstances": []}
        raise RuntimeError(
            f"aws rds describe-db-instances failed for {instance_id!r}: {proc.stderr.strip()}"
        )
    return json.loads(proc.stdout)


# Parameter-group apply states that mean the change is settled or in flight. Any
# other state (pending-reboot, failed-to-apply, error, pending-database-upgrade,
# removing) means a static parameter change was accepted but not yet applied —
# the deploy is incomplete in the same sense as a populated PendingModifiedValues.
_PARAMETER_GROUP_OK_STATUSES = frozenset({"in-sync", "applying"})


def _filtered_pending(instance_payload: dict) -> dict:
    """Build the pending-changes view for one DBInstance payload.

    Combines two AWS surfaces: `PendingModifiedValues` for instance-level
    fields (class, storage, engine version, dynamic params), and
    `DBParameterGroups[].ParameterApplyStatus` for static parameter-group
    fields. Both produce keys in the returned dict so downstream reporting and
    the `is_clean` check treat them uniformly.
    """
    pending = {
        k: v
        for k, v in (instance_payload.get("PendingModifiedValues") or {}).items()
        if v not in (None, [], {}, "")
    }
    for group in instance_payload.get("DBParameterGroups") or []:
        status = group.get("ParameterApplyStatus")
        if status and status not in _PARAMETER_GROUP_OK_STATUSES:
            name = group.get("DBParameterGroupName") or "<unknown>"
            pending[f"DBParameterGroup[{name}]"] = status
    return pending


def check_instance(
    instance_id: str,
    aws_describe: AwsDescribeFn = _default_aws_describe,
    sleep: SleepFn = time.sleep,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> InstanceCheck:
    """Return an InstanceCheck describing whether `instance_id` has pending mods.

    Polls AWS up to `max_attempts` times (sleeping `poll_interval` seconds
    between attempts) while RDS reports a transitional `DBInstanceStatus` and
    pending values are present. As soon as the status reaches a terminal value
    or pending becomes empty, returns the verdict immediately. If the poll
    budget is exhausted while the instance is still transitioning, returns a
    failing InstanceCheck describing the timeout — that is treated as a real
    deploy failure because operators need to investigate stuck modifies.
    """
    last_payload: dict | None = None
    last_pending: dict = {}
    for attempt in range(max(1, max_attempts)):
        response = aws_describe(instance_id)
        instances = response.get("DBInstances") or []
        if not instances:
            return InstanceCheck(
                instance_id=instance_id,
                error=f"RDS instance {instance_id!r} not found",
            )
        last_payload = instances[0]
        last_pending = _filtered_pending(last_payload)
        status = last_payload.get("DBInstanceStatus")

        # Terminal verdict: either the instance settled (no pending values) or
        # it left transitional states with pending values still queued.
        if not last_pending:
            return InstanceCheck(instance_id=instance_id, pending={})
        if status not in _TRANSITIONAL_STATUSES:
            return InstanceCheck(instance_id=instance_id, pending=last_pending)

        is_last_attempt = attempt == max(1, max_attempts) - 1
        if is_last_attempt:
            break
        sleep(poll_interval)

    status_msg = (
        last_payload.get("DBInstanceStatus") if last_payload is not None else "unknown"
    )
    return InstanceCheck(
        instance_id=instance_id,
        pending=last_pending,
        error=(
            f"RDS instance {instance_id!r} did not settle within "
            f"{max_attempts * poll_interval:.0f}s (DBInstanceStatus={status_msg!r}); "
            "pending modifications still present"
        ),
    )


def collect_instance_ids_from_tf_outputs_payload(payload: dict) -> list[str]:
    """Extract DB instance IDs from a parsed `terraform output -json` payload.

    Returns the value of every output whose key equals or ends with
    `db_instance_id`. Empty if no such outputs exist; the caller decides
    whether that is an error.
    """
    ids: list[str] = []
    for key, value in payload.items():
        if not (key == "db_instance_id" or key.endswith("_db_instance_id")):
            continue
        raw = value.get("value") if isinstance(value, dict) else value
        if isinstance(raw, str) and raw:
            ids.append(raw)
    return ids


def collect_instance_ids_from_tf_outputs(outputs_path: Path) -> list[str]:
    """Extract DB instance IDs from a `terraform output -json` JSON file."""
    payload = json.loads(outputs_path.read_text(encoding="utf-8"))
    return collect_instance_ids_from_tf_outputs_payload(payload)


def _terraform_outputs_payload(working_dir: Path) -> dict:
    """Run `terraform output -json` in `working_dir` and return the parsed dict.

    The output is held in memory and never written to disk: Terraform's JSON
    output may include outputs marked `sensitive`, and we have no need for
    anything other than the DB instance IDs.
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
        raise RuntimeError(
            f"terraform output -json failed in {working_dir}: {proc.stderr.strip()}"
        )
    return json.loads(proc.stdout)


def main(
    instance_ids: Iterable[str],
    aws_describe: AwsDescribeFn = _default_aws_describe,
    out_stream: TextIO = sys.stdout,
    sleep: SleepFn = time.sleep,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> int:
    ids = [i for i in instance_ids if i]
    if not ids:
        out_stream.write(
            "ERROR: no RDS instance IDs supplied. "
            "Pass IDs as positional args or use --tf-outputs-from <dir>.\n"
        )
        return 2

    failures: list[InstanceCheck] = []
    for instance_id in ids:
        result = check_instance(
            instance_id,
            aws_describe=aws_describe,
            sleep=sleep,
            max_attempts=max_attempts,
            poll_interval=poll_interval,
        )
        if result.is_clean:
            out_stream.write(f"OK    {instance_id} — no pending modifications\n")
            continue
        failures.append(result)
        if result.error:
            out_stream.write(f"FAIL  {instance_id} — {result.error}\n")
        else:
            fields = ", ".join(
                f"{k}=<redacted>" if k in _SECRET_PENDING_FIELDS else f"{k}={v!r}"
                for k, v in sorted(result.pending.items())
            )
            out_stream.write(f"FAIL  {instance_id} — pending: {fields}\n")

    if failures:
        out_stream.write(
            "\nOne or more RDS instances have unapplied changes after `terraform apply`.\n"
            "This means the deploy is incomplete: AWS accepted the change but is\n"
            "holding it for the maintenance window, or RDS did not finish the modify\n"
            "within the bounded poll window. Either set the relevant module-level\n"
            "`apply_immediately` input to `true` for this environment, or roll the\n"
            "change forward through the configured maintenance window.\n"
        )
        return 1
    return 0


def _build_argv_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail if any named RDS instance has pending modifications.",
    )
    parser.add_argument(
        "instance_ids",
        nargs="*",
        help="RDS DBInstanceIdentifier values to check",
    )
    parser.add_argument(
        "--tf-outputs-from",
        type=Path,
        default=None,
        help="Terraform working directory; runs `terraform output -json` and "
        "uses every output whose key ends with `db_instance_id`.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help=f"Maximum poll attempts per instance (default {DEFAULT_MAX_ATTEMPTS}).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Seconds between poll attempts (default {DEFAULT_POLL_INTERVAL}).",
    )
    return parser


def _entry() -> int:
    parser = _build_argv_parser()
    args = parser.parse_args()

    ids: list[str] = list(args.instance_ids)
    if args.tf_outputs_from is not None:
        payload = _terraform_outputs_payload(args.tf_outputs_from)
        ids.extend(collect_instance_ids_from_tf_outputs_payload(payload))

    return main(
        ids,
        max_attempts=args.max_attempts,
        poll_interval=args.poll_interval,
    )


if __name__ == "__main__":
    sys.exit(_entry())
