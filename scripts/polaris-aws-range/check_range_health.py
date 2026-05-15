#!/usr/bin/env python3
"""Range-by-range health check for BSides Ottawa Polaris event.

Runs a read-only inspection on every polaris-vm EC2 instance via SSM
RunCommand and compiles a markdown report. Designed to catch anything
the post-provision scripts (apply_splice_watcher.py +
apply_kali_bedrock_shard.py) could have disturbed, as well as generic
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

Targeting: same AMI-based discovery as apply_splice_watcher.py.
Alternatively pass --instance-ids.

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
import base64
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import boto3
from botocore.exceptions import ClientError

EXPECTED_CONTAINER_COUNT = 22
FLAG_CRITICAL_CONTAINERS = ["a5-scada", "a9-splice", "a0-website", "a14-kali"]
KALI_ENV_KEYS = [
    "CLAUDE_CODE_USE_BEDROCK",
    "AWS_REGION",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
]

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "health_report.md"

# Bash run on each polaris-vm. Emits key=value|key=value|... record to stdout.
# Boolean-ish fields use 1/0; string fields are space-free tokens.
INNER = r"""#!/bin/bash
set -u

out=""
add() { out="${out}${out:+|}${1}=${2}"; }

# host identity
add host "$(hostname)"
inst_id=$(curl -s --max-time 3 -H "X-aws-ec2-metadata-token: $(curl -s --max-time 3 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token)" http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo "?")
add instance_id "$inst_id"

# docker container count
running=$(sudo docker ps -q | wc -l | tr -d ' ')
add container_count "$running"
exited=$(sudo docker ps -a --filter status=exited --filter status=dead --format '{{.Names}}' | paste -sd, - )
exited=${exited:-none}
add exited_containers "$exited"

# a14-kali container running
kali_state=$(sudo docker inspect -f '{{.State.Status}}' a14-kali 2>/dev/null || echo missing)
add a14_state "$kali_state"

# a14-kali on splice-link?
if [[ "$kali_state" == "running" ]]; then
  on_splice=$(sudo docker inspect a14-kali --format '{{json .NetworkSettings.Networks}}' 2>/dev/null | grep -q 'splice-link' && echo 1 || echo 0)
else
  on_splice=0
fi
add a14_on_splice "$on_splice"

# a14-kali profile.d file
if [[ "$kali_state" == "running" ]]; then
  profile_ok=$(sudo docker exec a14-kali test -r /etc/profile.d/claude-bedrock.sh && echo 1 || echo 0)
else
  profile_ok=0
fi
add bedrock_profile "$profile_ok"

# presence of each required env key (no values, just 1/0)
if [[ "$profile_ok" == "1" ]]; then
  for key in CLAUDE_CODE_USE_BEDROCK AWS_REGION ANTHROPIC_MODEL ANTHROPIC_SMALL_FAST_MODEL; do
    present=$(sudo docker exec a14-kali grep -q "^export ${key}=" /etc/profile.d/claude-bedrock.sh && echo 1 || echo 0)
    add "env_${key}" "$present"
  done
  # static keys are only set for Account B shards — don't require them
  has_ak=$(sudo docker exec a14-kali grep -q '^export AWS_ACCESS_KEY_ID=' /etc/profile.d/claude-bedrock.sh && echo 1 || echo 0)
  add env_AWS_ACCESS_KEY_ID "$has_ak"
else
  for key in CLAUDE_CODE_USE_BEDROCK AWS_REGION ANTHROPIC_MODEL ANTHROPIC_SMALL_FAST_MODEL AWS_ACCESS_KEY_ID; do
    add "env_${key}" 0
  done
fi

# /etc/hosts entry
if [[ "$kali_state" == "running" ]]; then
  hosts_ok=$(sudo docker exec a14-kali grep -q 'bedrock-runtime.us-east-2.amazonaws.com' /etc/hosts && echo 1 || echo 0)
else
  hosts_ok=0
fi
add hosts_override "$hosts_ok"

# splice watcher systemd
sv_state=$(systemctl is-active polaris-splice-watcher.service 2>/dev/null || echo missing)
add splice_watcher "$sv_state"

# flag-critical containers
for name in a5-scada a9-splice a0-website; do
  state=$(sudo docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo missing)
  add "${name//-/_}_state" "$state"
done

echo "__RECORD__${out}__END__"
"""


@dataclass(frozen=True)
class Target:
    instance_id: str
    vpc_id: str
    name: str
    range_id: str
    user_id: str


@dataclass
class RangeReport:
    instance_id: str
    range_id: str
    user_id: str
    fields: dict[str, str]

    @property
    def ok(self) -> bool:
        return not self.issues()

    def issues(self) -> list[str]:
        probs: list[str] = []
        probs.extend(self._container_count_issue())
        probs.extend(self._exited_containers_issue())
        probs.extend(self._a14_kali_issues())
        probs.extend(self._bedrock_env_issues())
        probs.extend(self._splice_watcher_issue())
        probs.extend(self._other_container_state_issues())
        return probs

    def _container_count_issue(self) -> list[str]:
        cc = self.fields.get("container_count", "?")
        if cc != str(EXPECTED_CONTAINER_COUNT):
            return [f"container_count={cc}/{EXPECTED_CONTAINER_COUNT}"]
        return []

    def _exited_containers_issue(self) -> list[str]:
        ex = self.fields.get("exited_containers", "")
        if ex and ex != "none":
            return [f"exited=[{ex}]"]
        return []

    def _a14_kali_issues(self) -> list[str]:
        probs: list[str] = []
        if self.fields.get("a14_state") != "running":
            probs.append(f"a14-kali={self.fields.get('a14_state')}")
        if self.fields.get("a14_on_splice") == "1":
            probs.append("a14 still on splice-link (watcher didn't disconnect)")
        return probs

    def _bedrock_env_issues(self) -> list[str]:
        probs: list[str] = []
        if self.fields.get("bedrock_profile") != "1":
            probs.append("missing /etc/profile.d/claude-bedrock.sh")
        for k in KALI_ENV_KEYS:
            if self.fields.get(f"env_{k}") != "1":
                probs.append(f"missing env {k}")
        if self.fields.get("hosts_override") != "1":
            probs.append("missing /etc/hosts bedrock-runtime entry")
        return probs

    def _splice_watcher_issue(self) -> list[str]:
        sw = self.fields.get("splice_watcher")
        if sw != "active":
            return [f"splice-watcher={sw}"]
        return []

    def _other_container_state_issues(self) -> list[str]:
        probs: list[str] = []
        for name in ("a5_scada_state", "a9_splice_state", "a0_website_state"):
            if self.fields.get(name) != "running":
                probs.append(f"{name.replace('_state', '')}={self.fields.get(name)}")
        return probs


def resolve_polaris_ami_id(ssm_client) -> str:
    try:
        resp = ssm_client.get_parameter(Name="/shifter/ami/polaris-vm")
    except ClientError as e:
        raise SystemExit(f"failed to read SSM /shifter/ami/polaris-vm: {e}") from e
    return resp["Parameter"]["Value"]


def discover_targets(ec2_client, ami_id: str, vpc_id: str | None) -> list[Target]:
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
                tags = {t["Key"]: t["Value"] for t in (inst.get("Tags") or [])}
                targets.append(
                    Target(
                        instance_id=inst["InstanceId"],
                        vpc_id=inst["VpcId"],
                        name=tags.get("Name", ""),
                        range_id=tags.get("shifter:range_id", ""),
                        user_id=tags.get("shifter:user_id", ""),
                    )
                )
    return targets


def batched(seq: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def send_and_wait(ssm_client, instance_ids: list[str], script: str, timeout_s: int = 300) -> dict[str, dict]:
    resp = ssm_client.send_command(
        InstanceIds=instance_ids,
        DocumentName="AWS-RunShellScript",
        Comment="polaris range health check",
        Parameters={"commands": [script], "executionTimeout": [str(timeout_s)]},
        MaxConcurrency="50",
        MaxErrors="100%",
        TimeoutSeconds=timeout_s,
    )
    cmd_id = resp["Command"]["CommandId"]
    terminal = {"Success", "Cancelled", "TimedOut", "Failed"}
    time.sleep(2.0)
    results: dict[str, dict] = {}
    while True:
        results.clear()
        paginator = ssm_client.get_paginator("list_command_invocations")
        for page in paginator.paginate(CommandId=cmd_id, Details=True, MaxResults=50):
            for inv in page["CommandInvocations"]:
                plugin_out = ""
                plugin_err = ""
                for plugin in inv.get("CommandPlugins") or []:
                    plugin_out = plugin.get("Output", "") or plugin_out
                    plugin_err = plugin.get("StandardErrorContent", "") or plugin_err
                results[inv["InstanceId"]] = {
                    "Status": inv["Status"],
                    "StandardOutputContent": plugin_out,
                    "StandardErrorContent": plugin_err,
                }
        pending = [iid for iid, r in results.items() if r["Status"] not in terminal]
        if not pending and results:
            return results
        time.sleep(5)


def parse_record(stdout: str) -> dict[str, str]:
    start = stdout.find("__RECORD__")
    end = stdout.find("__END__")
    if start == -1 or end == -1:
        return {}
    body = stdout[start + len("__RECORD__") : end]
    out: dict[str, str] = {}
    for part in body.split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


def write_report(targets: list[Target], reports: list[RangeReport], out_path: Path, verbose: bool) -> None:
    ok = [r for r in reports if r.ok]
    bad = [r for r in reports if not r.ok]

    lines: list[str] = []
    lines.append("# Polaris range health report")
    lines.append("")
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(tz=timezone.utc).replace(microsecond=0)
    now_edt = now_utc - timedelta(hours=4)
    lines.append(f"Generated: {now_utc.isoformat()} / {now_edt.strftime('%H:%M EDT')}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Discovered polaris-vm ranges: {len(targets)}")
    lines.append(f"- Checked: {len(reports)}")
    lines.append(f"- Healthy: **{len(ok)}**")
    lines.append(f"- With issues: **{len(bad)}**")
    lines.append(f"- Unreachable (SSM failure): {len(targets) - len(reports)}")
    lines.append("")

    if bad:
        lines.append("## Issues")
        lines.append("")
        lines.append("| range | user | instance | problems |")
        lines.append("|---|---|---|---|")
        for r in sorted(bad, key=lambda x: (int(x.range_id) if x.range_id.isdigit() else 999, x.instance_id)):
            probs = "; ".join(r.issues())
            lines.append(f"| {r.range_id} | {r.user_id} | {r.instance_id} | {probs} |")
        lines.append("")
    else:
        lines.append("## Issues")
        lines.append("")
        lines.append("None. 🟢")
        lines.append("")

    if verbose:
        lines.append("## All ranges")
        lines.append("")
        lines.append("| range | user | instance | ok | containers | a14 | splice-watcher | shard model |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in sorted(reports, key=lambda x: (int(x.range_id) if x.range_id.isdigit() else 999, x.instance_id)):
            ok_m = "🟢" if r.ok else "🔴"
            cc = r.fields.get("container_count", "?")
            a14 = r.fields.get("a14_state", "?")
            sw = r.fields.get("splice_watcher", "?")
            lines.append(f"| {r.range_id} | {r.user_id} | {r.instance_id} | {ok_m} | {cc}/22 | {a14} | {sw} | - |")
        lines.append("")

    out_path.write_text("\n".join(lines) + "\n")


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
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    ec2 = session.client("ec2")
    ssm = session.client("ssm")

    if args.instance_ids:
        ids = [s.strip() for s in args.instance_ids.split(",") if s.strip()]
        targets = [Target(instance_id=i, vpc_id="?", name="?", range_id="?", user_id="?") for i in ids]
    else:
        ami = args.ami_id or resolve_polaris_ami_id(ssm)
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
            results = send_and_wait(ssm, chunk, INNER)
        except ClientError as e:
            print(f"  SendCommand failed: {e}", file=sys.stderr)
            continue
        for iid, res in results.items():
            if res["Status"] != "Success":
                continue
            rec = parse_record(res.get("StandardOutputContent", ""))
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
