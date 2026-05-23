#!/usr/bin/env python3
"""Range-by-range health check for BSides Ottawa Polaris event.

Runs a read-only inspection on every polaris-vm EC2 instance via SSM
RunCommand and compiles a markdown report. Designed to catch anything
the PolarisRangeBootstrapPlan setup steps (splice watcher install +
kali bedrock shard) could have disturbed, as well as generic
provisioning misses.

Checks (per range):

- docker container count == 22 (polaris compose stack)
- any exited/dead containers
- a14-kali container is running
- a14-kali /etc/profile.d/claude-bedrock.sh exists and has the right
  keys set (values masked)
- a14-kali /etc/hosts has the bedrock-runtime VPCE override
- a14-kali is NOT connected to the splice-link docker network (the
  watcher should have disconnected it; the splice attaches dynamically
  when flag 19 fires)
- polaris-splice-watcher.service is active
- a5-scada, a9-splice, a0-website containers are running (spot check
  on the flag-bearing services — if any are dead the scenario is
  broken in a way that participants will notice)

The bash hotfix emits a single-line pipe-delimited record per host so
the Python side just splits & tallies. Never reads or logs secret
values (keys are boolean-present only).

Targeting: AMI-based discovery against the /shifter/ami/polaris-vm SSM
parameter. Alternatively pass --instance-ids.

Per-host probe script, target discovery, report writer, and the issue
model live in :mod:`range_health`; the shared AWS / SSM transport lives in
:mod:`common`. This entrypoint just wires CLI args, runs the SSM fan-out
in batches, and writes the report.

Usage::

    python3 check_range_health.py --profile panw-shifter-dev-workstation

    # full per-range detail table (not just issues)
    python3 check_range_health.py --profile panw-shifter-dev-workstation --verbose

    # write report to an explicit path
    python3 check_range_health.py --profile panw-shifter-dev-workstation \\
        --output /tmp/health.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from botocore.exceptions import ClientError

from common import PolarisAwsContext, SsmExecutor, SsmTimeout
from range_health import (
    HEALTH_PROBE_SCRIPT,
    RangeReport,
    Target,
    batched,
    discover_targets,
    parse_record,
    resolve_polaris_ami_id,
    write_report,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "health_report.md"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile")
    p.add_argument("--region", default="us-east-2")
    p.add_argument("--ami-id", help="Override polaris-vm AMI")
    p.add_argument("--vpc-id", help="Restrict discovery to this VPC")
    p.add_argument("--instance-ids", help="Comma-separated IDs; skips AMI discovery")
    p.add_argument("--batch-size", type=int, default=50)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--verbose", action="store_true", help="Include full per-range table.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    ctx = PolarisAwsContext(profile=args.profile, region=args.region)
    ec2 = ctx.ec2()
    executor = SsmExecutor(ctx.ssm(), poll_interval_s=5.0, default_timeout_s=300)

    if args.instance_ids:
        ids = [s.strip() for s in args.instance_ids.split(",") if s.strip()]
        targets = [Target(instance_id=i, vpc_id="?", name="?", range_id="?", user_id="?") for i in ids]
    else:
        ami = args.ami_id or resolve_polaris_ami_id(ctx.ssm())
        print(f"discovering polaris-vms (ami={ami})...", flush=True)
        targets = discover_targets(ec2, ami, args.vpc_id)
    print(f"{len(targets)} target(s)", flush=True)
    if not targets:
        return 0

    id_to_target = {t.instance_id: t for t in targets}
    ids = list(id_to_target.keys())
    reports: list[RangeReport] = []

    for batch_num, chunk in enumerate(batched(ids, args.batch_size), start=1):
        print(f"batch {batch_num}: {len(chunk)} instance(s)...", flush=True)
        try:
            results = executor.run_bash_batch(
                chunk,
                HEALTH_PROBE_SCRIPT,
                timeout_s=300,
                comment="polaris range health check",
            )
        except ClientError as e:
            print(f"  SendCommand failed: {e}", file=sys.stderr)
            continue
        except SsmTimeout as e:
            # One bad/missing instance must not suppress the fleet report.
            # The report contract already tracks any target without a record
            # as "Unreachable (SSM failure)" via len(targets) - len(reports),
            # so we drop the batch and keep going.
            print(f"  batch timed out, treating affected instances as unreachable: {e}", file=sys.stderr)
            continue
        for iid, res in results.items():
            if res.status != "Success":
                continue
            rec = parse_record(res.stdout)
            if not rec:
                continue
            t = id_to_target[iid]
            reports.append(
                RangeReport(
                    instance_id=iid,
                    range_id=t.range_id,
                    user_id=t.user_id,
                    fields=rec,
                )
            )

    write_report(targets, reports, args.output, args.verbose)
    bad = [r for r in reports if not r.ok]
    print(f"\nreport: {args.output}")
    print(f"healthy: {len(reports) - len(bad)} / {len(reports)}   unreachable: {len(targets) - len(reports)}")
    if bad:
        print("issues:")
        for r in bad[:20]:
            print(f"  range={r.range_id} user={r.user_id} {r.instance_id}: {'; '.join(r.issues())[:160]}")
    return 0 if not bad and len(reports) == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())
