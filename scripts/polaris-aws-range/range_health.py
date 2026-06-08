"""Polaris range health-check data model + IO (issue #691).

Extracted from ``check_range_health.py`` so the script becomes a thin CLI
over (a) ``common.SsmExecutor`` for the SSM fan-out and (b) this module
for target discovery, the per-host pipe-delimited record parser, the
issue-detection model, and the markdown report writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from botocore.exceptions import ClientError

EXPECTED_CONTAINER_COUNT = 17
FLAG_CRITICAL_CONTAINERS = ("a5-scada", "a9-splice", "a0-website", "a14-kali")
KALI_ENV_KEYS = (
    "CLAUDE_CODE_USE_BEDROCK",
    "AWS_REGION",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
)

POLARIS_AMI_SSM_PARAM = "/shifter/ami/polaris-vm"

# Bash run on each polaris-vm. Emits key=value|key=value|... record to stdout.
# Boolean-ish fields use 1/0; string fields are space-free tokens. The pipe
# format keeps the parser trivial and avoids any string-quoting failure
# modes that have bitten richer envelopes in the past.
HEALTH_PROBE_SCRIPT = r"""#!/bin/bash
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
    """Identifying info for one polaris-vm EC2 instance."""

    instance_id: str
    vpc_id: str
    name: str
    range_id: str
    user_id: str


@dataclass
class RangeReport:
    """Per-instance health report assembled from a parsed bash record."""

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


def parse_record(stdout: str) -> dict[str, str]:
    """Parse the ``__RECORD__k=v|k=v__END__`` envelope written by the bash probe."""
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


def resolve_polaris_ami_id(ssm_client, *, parameter_name: str = POLARIS_AMI_SSM_PARAM) -> str:
    try:
        resp = ssm_client.get_parameter(Name=parameter_name)
    except ClientError as e:
        raise SystemExit(f"failed to read SSM {parameter_name}: {e}") from e
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


def write_report(
    targets: list[Target],
    reports: list[RangeReport],
    out_path: Path,
    verbose: bool,
) -> None:
    ok = [r for r in reports if r.ok]
    bad = [r for r in reports if not r.ok]

    lines: list[str] = []
    lines.append("# Polaris range health report")
    lines.append("")
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
        for r in sorted(
            bad,
            key=lambda x: (int(x.range_id) if x.range_id.isdigit() else 999, x.instance_id),
        ):
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
        for r in sorted(
            reports,
            key=lambda x: (int(x.range_id) if x.range_id.isdigit() else 999, x.instance_id),
        ):
            ok_m = "🟢" if r.ok else "🔴"
            cc = r.fields.get("container_count", "?")
            a14 = r.fields.get("a14_state", "?")
            sw = r.fields.get("splice_watcher", "?")
            lines.append(
                f"| {r.range_id} | {r.user_id} | {r.instance_id} | {ok_m} | {cc}/{EXPECTED_CONTAINER_COUNT} | {a14} | {sw} | - |"
            )
        lines.append("")

    out_path.write_text("\n".join(lines) + "\n")


__all__ = [
    "EXPECTED_CONTAINER_COUNT",
    "FLAG_CRITICAL_CONTAINERS",
    "HEALTH_PROBE_SCRIPT",
    "KALI_ENV_KEYS",
    "POLARIS_AMI_SSM_PARAM",
    "RangeReport",
    "Target",
    "batched",
    "discover_targets",
    "parse_record",
    "resolve_polaris_ami_id",
    "write_report",
]
