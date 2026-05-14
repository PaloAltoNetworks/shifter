#!/usr/bin/env python3
"""Apply polaris-vm post-bake hotfixes via SSM.

Skips the CI/CD + provisioner path — lets an operator roll fixes out to
already-deployed ranges directly. Does the same things the updated
PolarisRangeBootstrapPlan would do on a fresh range:

    1. `docker network disconnect` a14-kali from the baked splice-link
       pre-wire (discovers network name by suffix).
    2. Writes /usr/local/bin/polaris-splice-watcher.sh.
    3. Writes + enables + restarts
       /etc/systemd/system/polaris-splice-watcher.service.
    4. Drops /home/kali/.polaris/welcome.txt into the a14-kali container
       so the Start Here — Kali Warm-Up challenge is solvable on already-
       baked ranges.

Idempotent: re-running against an already-fixed range is a no-op apart
from restarting the watcher service and rewriting welcome.txt in place.

Targeting
---------
By default discovers every running EC2 instance whose AMI ID matches the
SSM parameter `/shifter/ami/polaris-vm`, optionally filtered to a single
VPC. Alternatively accepts an explicit list of instance IDs.

Rate limits
-----------
SSM SendCommand accepts up to 50 InstanceIds per call. This script
batches targets into chunks of --batch-size (default 50) and issues one
command per chunk. Within each command SSM runs the script on
--max-concurrency targets at a time (default 10) so we never flood a
single range-VPC NAT. One SendCommand API call per batch keeps us well
under the RunCommand API rate (throttled around ~40 req/s per account
per region). Polling uses ListCommandInvocations with a 5s backoff.

Usage
-----
    # Dry-run (show targets and exit)
    python3 apply_splice_watcher.py --vpc-id vpc-0123 --dry-run

    # Apply to every polaris-vm in the range VPC
    python3 apply_splice_watcher.py --vpc-id vpc-0123

    # Apply to an explicit list
    python3 apply_splice_watcher.py --instance-ids i-aaa,i-bbb,i-ccc

Environment: AWS creds from the usual boto3 chain. Default region
us-east-2 (override with --region).
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Iterable

import boto3
from botocore.exceptions import ClientError

# -----------------------------------------------------------------------------
# Bash hotfix that runs on each target instance.
#
# IMPORTANT: Kept self-contained so this script can be copied to any
# operator laptop without repo context. Any drift between this and
# shifter/engine/provisioner/plans/polaris_range_bootstrap.py's
# INSTALL_SPLICE_WATCHER_SCRIPT + the disconnect snippet in
# POLARIS_RANGE_BOOTSTRAP_SCRIPT must be resolved in favour of the
# bootstrap plan (which is the long-term source of truth for new ranges).
# -----------------------------------------------------------------------------
HOTFIX_SCRIPT = r"""#!/bin/bash
set -euo pipefail

echo "polaris splice hotfix: starting on $(hostname) at $(date -Iseconds)"

# 1. Strip the baked pre-wire: disconnect a14-kali from splice-link.
#    Compose prefixes network names with the project name ("build"), so
#    the real name is "build_splice-link"; discover by suffix in case
#    that ever changes. Non-fatal if the container isn't on it.
splice_net=$(docker network ls --format '{{.Name}}' | grep -E '(^|_)splice-link$' | head -n1 || true)
if [[ -z "$splice_net" ]]; then
  echo "polaris splice hotfix: no splice-link network found — is this a polaris-vm?" >&2
  exit 2
fi
if docker inspect a14-kali >/dev/null 2>&1; then
  docker network disconnect "$splice_net" a14-kali 2>/dev/null \
    && echo "polaris splice hotfix: disconnected a14-kali from $splice_net" \
    || echo "polaris splice hotfix: a14-kali was not on $splice_net (ok)"
else
  echo "polaris splice hotfix: a14-kali container not found" >&2
  exit 2
fi

# 2. Write the watcher. Quoted delimiter keeps the host shell away from
#    the inner $VARS and $(subst). The watcher uses dot-prefixed Go
#    template tokens only (no bare word-only placeholders) — irrelevant
#    here (no Jinja rendering) but keeps this file a drop-in match for
#    the bootstrap plan's heredoc.
WATCHER=/usr/local/bin/polaris-splice-watcher.sh
cat > "$WATCHER" <<'WATCHER_EOF'
#!/bin/bash
# polaris-splice-watcher: poll A5 HMI state; when the generator goes
# into thermal runaway (flag 19 earned), attach a14-kali to the
# splice-link docker network so the participant can reach a9-splice.
set -euo pipefail

# A5 container_name in scenario-dev/polaris/build/docker-compose.yml is
# "a5-scada" — verified empirically. Earlier "a5-scada-generator" default
# was the source of a silent failure at BSides Ottawa (2026-04): the
# watcher polled a non-existent container, never observed
# runaway_complete=true, never attached A14 to splice-link, and
# operators had to manually `docker network connect` per participant.
A5_CONTAINER="${A5_CONTAINER:-a5-scada}"
KALI_CONTAINER="${KALI_CONTAINER:-a14-kali}"
SPLICE_NETWORK="${SPLICE_NETWORK:-build_splice-link}"
SPLICE_IP="${SPLICE_IP:-172.20.60.140}"
POLL_INTERVAL_S="${POLL_INTERVAL_S:-10}"

poll_runaway_complete() {
  local body
  body=$(docker exec "$A5_CONTAINER" python3 -c \
    'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:8080/api/status", timeout=5).read().decode())' \
    2>/dev/null) || return 1
  [[ "$body" == *'"runaway_complete": true'* ]] || [[ "$body" == *'"runaway_complete":true'* ]]
}

is_connected() {
  docker inspect "$KALI_CONTAINER" \
    --format '{{json .NetworkSettings.Networks}}' 2>/dev/null \
    | grep -q "\"$SPLICE_NETWORK\""
}

connect_splice() {
  echo "polaris-splice-watcher: connecting $KALI_CONTAINER to $SPLICE_NETWORK ($SPLICE_IP)"
  docker network connect --ip "$SPLICE_IP" "$SPLICE_NETWORK" "$KALI_CONTAINER"
}

echo "polaris-splice-watcher: starting (network=$SPLICE_NETWORK, container=$KALI_CONTAINER)"

while true; do
  if poll_runaway_complete; then
    if ! is_connected; then
      if connect_splice; then
        echo "polaris-splice-watcher: splice established"
      else
        echo "polaris-splice-watcher: connect failed, will retry" >&2
      fi
    fi
  fi
  sleep "$POLL_INTERVAL_S"
done
WATCHER_EOF
chmod +x "$WATCHER"
echo "polaris splice hotfix: wrote $WATCHER"

# 3. Systemd unit.
cat > /etc/systemd/system/polaris-splice-watcher.service <<'UNIT_EOF'
[Unit]
Description=Polaris splice watcher (attaches a14-kali to splice-link on flag 19)
After=docker.service
Requires=docker.service

[Service]
Type=simple
ExecStart=/usr/local/bin/polaris-splice-watcher.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT_EOF

# 4. Enable + (re)start.
systemctl daemon-reload
systemctl enable polaris-splice-watcher.service >/dev/null 2>&1
systemctl restart polaris-splice-watcher.service
sleep 1
if ! systemctl is-active --quiet polaris-splice-watcher.service; then
  echo "polaris splice hotfix: service failed to start" >&2
  systemctl status polaris-splice-watcher.service --no-pager >&2 || true
  exit 1
fi

# 5. Drop the Start Here — Kali Warm-Up orientation file into a14-kali.
#    Mirror of scenario-dev/polaris/build/A14-kali/welcome.txt in the
#    repo; any drift between these copies should be resolved in favour
#    of the repo file (source of truth for fresh Kali bakes). Flag value
#    must match the one in scenario-dev/polaris/build/ctfd-onboarding.json.
if docker inspect a14-kali >/dev/null 2>&1; then
  docker exec a14-kali mkdir -p /home/kali/.polaris
  docker exec -i a14-kali tee /home/kali/.polaris/welcome.txt >/dev/null <<'WELCOME_EOF'
==========================================
  JOINT TASK FORCE POLARIS
  OPERATION NORTHSTORM — COMM CHECK
  Classification: SECRET // POLARIS EYES ONLY
==========================================

Welcome, Operator.

If you're reading this, you're inside your Kali box and your
comms are working. That's all the warm-up is checking.

Your first flag:

  FLAG{0a5c7e3f91b8d426}

Switch to your CTFd tab. Submit it. That's your first token
on the board.

When you're done, start with Mission 1 — Boreas. Everything
else you need lives on CTFd from here.

Good hunting.

— NORTHSTORM Command
WELCOME_EOF
  docker exec a14-kali chown -R kali:kali /home/kali/.polaris
  echo "polaris welcome file: dropped /home/kali/.polaris/welcome.txt"
else
  echo "polaris welcome file: a14-kali container not found; skipping" >&2
fi

echo "polaris splice + welcome hotfix: complete"
"""


@dataclass(frozen=True)
class Target:
    instance_id: str
    vpc_id: str
    name: str


def resolve_polaris_ami_id(ssm_client) -> str:
    """Read /shifter/ami/polaris-vm from SSM Parameter Store."""
    try:
        resp = ssm_client.get_parameter(Name="/shifter/ami/polaris-vm")
    except ClientError as e:
        raise SystemExit(
            f"failed to read SSM /shifter/ami/polaris-vm: {e}. "
            "Pass --ami-id explicitly to skip the lookup."
        ) from e
    return resp["Parameter"]["Value"]


def _extract_name_tag(inst: dict) -> str:
    """Return the `Name` tag value for an EC2 instance, or empty string."""
    for tag in inst.get("Tags") or []:
        if tag["Key"] == "Name":
            return tag["Value"]
    return ""


def discover_targets(ec2_client, ami_id: str, vpc_id: str | None) -> list[Target]:
    """List all running instances matching the polaris-vm AMI (and VPC)."""
    filters = [
        {"Name": "image-id", "Values": [ami_id]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ]
    if vpc_id:
        filters.append({"Name": "vpc-id", "Values": [vpc_id]})

    targets: list[Target] = []
    paginator = ec2_client.get_paginator("describe_instances")
    for page in paginator.paginate(Filters=filters):
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                targets.append(
                    Target(
                        instance_id=inst["InstanceId"],
                        vpc_id=inst["VpcId"],
                        name=_extract_name_tag(inst),
                    )
                )
    return targets


def batched(seq: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def send_hotfix_batch(
    ssm_client,
    instance_ids: list[str],
    script: str,
    max_concurrency: int,
    timeout_s: int,
) -> str:
    """Issue one SendCommand against up to 50 instance IDs."""
    resp = ssm_client.send_command(
        InstanceIds=instance_ids,
        DocumentName="AWS-RunShellScript",
        Comment="polaris splice-watcher + welcome hotfix",
        Parameters={"commands": [script], "executionTimeout": [str(timeout_s)]},
        MaxConcurrency=str(max_concurrency),
        # 3 failures per batch stops the batch. Prevents a bad AMI /
        # partial rollout from cascading.
        MaxErrors="3",
        TimeoutSeconds=timeout_s,
    )
    return resp["Command"]["CommandId"]


def wait_for_batch(ssm_client, command_id: str, poll_s: float = 5.0) -> dict[str, dict]:
    """Block until every invocation under command_id is in a terminal state.

    Returns {instance_id: {Status, StatusDetails, StandardErrorContent,
    StandardOutputContent}} (stdout/stderr trimmed to last ~500 chars).
    """
    terminal = {"Success", "Cancelled", "TimedOut", "Failed"}
    # First call waits until SSM has created invocations (can be racy
    # right after SendCommand).
    time.sleep(2.0)

    results: dict[str, dict] = {}
    while True:
        results.clear()
        paginator = ssm_client.get_paginator("list_command_invocations")
        for page in paginator.paginate(
            CommandId=command_id, Details=True, MaxResults=50
        ):
            for inv in page["CommandInvocations"]:
                plugin_out = ""
                plugin_err = ""
                for plugin in inv.get("CommandPlugins") or []:
                    plugin_out = plugin.get("Output", "") or plugin_out
                    plugin_err = plugin.get("StandardErrorContent", "") or plugin_err
                results[inv["InstanceId"]] = {
                    "Status": inv["Status"],
                    "StatusDetails": inv.get("StatusDetails", ""),
                    "StandardOutputContent": plugin_out[-500:],
                    "StandardErrorContent": plugin_err[-500:],
                }
        pending = [
            iid for iid, r in results.items() if r["Status"] not in terminal
        ]
        if not pending and results:
            return results
        time.sleep(poll_s)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--region", default="us-east-2")
    p.add_argument(
        "--ami-id",
        help="Override the AMI ID to target. Default: resolve /shifter/ami/polaris-vm.",
    )
    p.add_argument(
        "--vpc-id",
        help="Restrict discovery to this VPC (recommended in prod to avoid "
        "touching stale/legacy ranges).",
    )
    p.add_argument(
        "--instance-ids",
        help="Comma-separated instance IDs. Skips AMI/VPC discovery entirely.",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Instance IDs per SendCommand (SSM limit: 50).",
    )
    p.add_argument(
        "--max-concurrency",
        type=int,
        default=10,
        help="Within a batch, how many instances SSM runs the script on at once.",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Per-invocation execution timeout in seconds.",
    )
    p.add_argument("--dry-run", action="store_true", help="List targets and exit.")
    p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size < 1 or args.batch_size > 50:
        print("--batch-size must be 1..50 (SSM limit)", file=sys.stderr)
        return 2

    session = boto3.Session(region_name=args.region)
    ec2 = session.client("ec2")
    ssm = session.client("ssm")

    # --- Resolve targets ---
    if args.instance_ids:
        ids = [s.strip() for s in args.instance_ids.split(",") if s.strip()]
        targets = [Target(instance_id=i, vpc_id="?", name="?") for i in ids]
    else:
        ami_id = args.ami_id or resolve_polaris_ami_id(ssm)
        print(f"discovering instances: ami_id={ami_id} vpc_id={args.vpc_id or '(any)'}")
        targets = discover_targets(ec2, ami_id, args.vpc_id)

    if not targets:
        print("no targets found.")
        return 0

    print(f"\n{len(targets)} target(s):")
    for t in targets[:20]:
        print(f"  {t.instance_id}  vpc={t.vpc_id}  name={t.name!r}")
    if len(targets) > 20:
        print(f"  ... and {len(targets) - 20} more")

    if args.dry_run:
        print("\n--dry-run: no commands sent.")
        return 0

    if not args.yes:
        confirm = input(f"\napply splice-watcher hotfix to {len(targets)} instance(s)? [yes/NO] ").strip()
        if confirm.lower() not in {"yes", "y"}:
            print("aborted.")
            return 1

    # --- Send in batches ---
    instance_ids = [t.instance_id for t in targets]
    overall: dict[str, dict] = {}

    for batch_num, chunk in enumerate(batched(instance_ids, args.batch_size), start=1):
        print(f"\nbatch {batch_num}: {len(chunk)} instance(s) -> SendCommand")
        try:
            command_id = send_hotfix_batch(
                ssm,
                instance_ids=chunk,
                script=HOTFIX_SCRIPT,
                max_concurrency=args.max_concurrency,
                timeout_s=args.timeout,
            )
        except ClientError as e:
            print(f"  SendCommand failed: {e}", file=sys.stderr)
            for iid in chunk:
                overall[iid] = {"Status": "SendFailed", "StatusDetails": str(e)}
            continue
        print(f"  command_id={command_id}, waiting...")
        results = wait_for_batch(ssm, command_id)
        overall.update(results)

        succeeded = sum(1 for r in results.values() if r["Status"] == "Success")
        failed = sum(1 for r in results.values() if r["Status"] != "Success")
        print(f"  batch {batch_num} done: {succeeded} success, {failed} non-success")

    # --- Summary ---
    print("\n=== summary ===")
    succeeded = [iid for iid, r in overall.items() if r["Status"] == "Success"]
    failed = {iid: r for iid, r in overall.items() if r["Status"] != "Success"}
    print(f"success: {len(succeeded)} / {len(overall)}")

    if failed:
        print("\nfailures:")
        for iid, r in failed.items():
            err = r.get("StandardErrorContent", "")[-200:].strip()
            details = r.get("StatusDetails", "")
            print(f"  {iid}  status={r['Status']}  details={details}")
            if err:
                print(f"    stderr: {err}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
