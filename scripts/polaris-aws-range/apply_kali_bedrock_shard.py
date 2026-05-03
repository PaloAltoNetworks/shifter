#!/usr/bin/env python3
"""Configure Claude Code inside a14-kali on deployed polaris-vm ranges to
shard Bedrock load across {Account A, Account B} x {Sonnet 4.5, 4.6} x
{US CRIS, Global CRIS} inference profiles.

Skips the CI/CD + provisioner path so we can roll shard config out
to already-deployed ranges before the BSides Ottawa event. Does the
same thing the (not-yet-written) PolarisRangeBootstrapPlan extension
will do on a fresh range:

    1. Pick a shard for this range from its ``shifter:user_id`` EC2 tag
       (``user_id % 8``).
    2. If the shard targets Account B, fetch static IAM-user keys from
       Account A Secrets Manager (secret ``shifter/polaris/backup-bedrock``).
       Otherwise let Claude Code inherit the polaris-vm instance-profile
       role (Account A Bedrock perms already granted).
    3. Write ``/etc/profile.d/claude-bedrock.sh`` inside ``a14-kali``
       with ``CLAUDE_CODE_USE_BEDROCK=1``, ``AWS_REGION=us-east-2``,
       ``ANTHROPIC_MODEL``, ``ANTHROPIC_SMALL_FAST_MODEL``, and (for B
       shards) ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``.
    4. Inject an ``/etc/hosts`` entry for
       ``bedrock-runtime.us-east-2.amazonaws.com`` pointing at the VPC
       endpoint private IP. The range's custom compose ``dns`` service
       returns public IPs which the private subnet cannot reach; this
       hosts override bypasses it.
    5. Sanity-check with ``claude -p "reply ok"`` and log the output.

Idempotent: re-running reasserts the profile file + hosts entry. No
container restart required — Claude Code sources the profile on every
new interactive shell.

Targeting
---------
By default discovers every running EC2 instance whose AMI ID matches
the SSM parameter ``/shifter/ami/polaris-vm``, optionally filtered to
a VPC. Alternatively accepts an explicit list of instance IDs.

Shard assignment
----------------
Shard index = int(shifter:user_id tag) % 8. The 8 shards are:

    0  Account A  us.anthropic.claude-sonnet-4-6                        (US CRIS)
    1  Account A  global.anthropic.claude-sonnet-4-6                    (Global CRIS)
    2  Account A  us.anthropic.claude-sonnet-4-5-20250929-v1:0          (US CRIS)
    3  Account A  global.anthropic.claude-sonnet-4-5-20250929-v1:0      (Global CRIS)
    4  Account B  us.anthropic.claude-sonnet-4-6                        (US CRIS)
    5  Account B  global.anthropic.claude-sonnet-4-6                    (Global CRIS)
    6  Account B  us.anthropic.claude-sonnet-4-5-20250929-v1:0          (US CRIS)
    7  Account B  global.anthropic.claude-sonnet-4-5-20250929-v1:0      (Global CRIS)

Small/fast Haiku routes through the matching {account, us/global}
bucket. Account A shards call without static creds (instance profile);
Account B shards embed static creds fetched from Secrets Manager.

Rate limits
-----------
Same pattern as apply_splice_watcher.py: batches of up to 50 instances
per SendCommand call, ``--max-concurrency`` targets per batch. One
SSM RunCommand per unique shard config, keyed by (account, model,
fast_model).

Usage
-----
    # Dry-run (show shard assignments, no changes)
    python3 apply_kali_bedrock_shard.py --vpc-id vpc-0123 --dry-run

    # Apply to all polaris-vms in a VPC
    python3 apply_kali_bedrock_shard.py --vpc-id vpc-0123

    # Apply to an explicit list, forcing a specific shard (testing only)
    python3 apply_kali_bedrock_shard.py --instance-ids i-aaa,i-bbb \\
        --force-shard 3

Environment: AWS creds from the usual boto3 chain (Account A). Default
region us-east-2 (override with --region).
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
# Shard table
# -----------------------------------------------------------------------------

SHARD_TABLE = [
    # (account_id, model, fast_model)
    ("158151907940", "us.anthropic.claude-sonnet-4-6",                      "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("158151907940", "global.anthropic.claude-sonnet-4-6",                  "global.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("158151907940", "us.anthropic.claude-sonnet-4-5-20250929-v1:0",        "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("158151907940", "global.anthropic.claude-sonnet-4-5-20250929-v1:0",    "global.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("811259913580", "us.anthropic.claude-sonnet-4-6",                      "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("811259913580", "global.anthropic.claude-sonnet-4-6",                  "global.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("811259913580", "us.anthropic.claude-sonnet-4-5-20250929-v1:0",        "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("811259913580", "global.anthropic.claude-sonnet-4-5-20250929-v1:0",    "global.anthropic.claude-haiku-4-5-20251001-v1:0"),
]

ACCOUNT_A_ID = "158151907940"
ACCOUNT_B_ID = "811259913580"
ACCOUNT_B_SECRET_ID = "shifter/polaris/backup-bedrock"

# -----------------------------------------------------------------------------
# Inner script (templated per shard).
#
# IMPORTANT: Kept self-contained so this script can be copied to any
# operator laptop without repo context. Any drift between this and
# the (forthcoming) PolarisRangeBootstrapPlan extension must be resolved
# in favour of the bootstrap plan.
# -----------------------------------------------------------------------------
INNER_SCRIPT_TEMPLATE = r"""#!/bin/bash
set -euo pipefail

echo "kali bedrock shard hotfix: starting on $(hostname) at $(date -Iseconds)"
echo "kali bedrock shard hotfix: shard=__SHARD_IDX__ account=__ACCOUNT_ID__ model=__MODEL__"

# 1. Resolve Bedrock VPC endpoint private IP (so the container /etc/hosts
#    override points at a real reachable address). Queries the Amazon-
#    provided DNS directly to sidestep the scenario's custom dns
#    container (which returns public IPs that a private subnet cannot
#    reach).
BEDROCK_FQDN="bedrock-runtime.us-east-2.amazonaws.com"
BEDROCK_IP="$(getent hosts "$BEDROCK_FQDN" | awk '{print $1; exit}')"
# If the host resolver already returned a private RFC1918 IP we can
# trust it (VPC resolver served a VPCE IP). Otherwise fall back to
# querying the Amazon DNS at 169.254.169.253 directly.
case "$BEDROCK_IP" in
  10.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*|192.168.*) : ;;
  *)
    if command -v dig >/dev/null 2>&1; then
      BEDROCK_IP="$(dig +short @169.254.169.253 "$BEDROCK_FQDN" | grep -E '^10\.' | head -n1)"
    fi
    ;;
esac
if [[ -z "$BEDROCK_IP" ]]; then
  echo "kali bedrock shard hotfix: could not resolve $BEDROCK_FQDN to a private IP" >&2
  exit 2
fi
echo "kali bedrock shard hotfix: bedrock VPCE IP = $BEDROCK_IP"

# 2. Build the profile.d file on the host in a tmp file, never printing
#    any secret to stdout.
PROFILE_FILE="$(mktemp)"
chmod 600 "$PROFILE_FILE"
{
  echo '# Managed by apply_kali_bedrock_shard.py — do not edit manually.'
  echo 'export CLAUDE_CODE_USE_BEDROCK=1'
  echo 'export AWS_REGION=us-east-2'
  echo 'export ANTHROPIC_MODEL=__MODEL__'
  echo 'export ANTHROPIC_SMALL_FAST_MODEL=__FAST_MODEL__'
} > "$PROFILE_FILE"

if [[ "__USE_SECRET__" == "1" ]]; then
  SECRET_JSON="$(aws secretsmanager get-secret-value \
    --secret-id __SECRET_ID__ --region us-east-2 \
    --query SecretString --output text)"
  SECRET_JSON="$SECRET_JSON" python3 - "$PROFILE_FILE" <<'PYEOF'
import json, os, sys
d = json.loads(os.environ["SECRET_JSON"])
with open(sys.argv[1], "a") as f:
    f.write("export AWS_ACCESS_KEY_ID=" + d["aws_access_key_id"] + "\n")
    f.write("export AWS_SECRET_ACCESS_KEY=" + d["aws_secret_access_key"] + "\n")
PYEOF
  unset SECRET_JSON
fi

# 3. Install in container + set perms. Use docker cp which preserves
#    contents without ever echoing them.
docker cp "$PROFILE_FILE" a14-kali:/etc/profile.d/claude-bedrock.sh
docker exec a14-kali chmod 644 /etc/profile.d/claude-bedrock.sh
shred -u "$PROFILE_FILE" 2>/dev/null || rm -f "$PROFILE_FILE"

# 4. Inject /etc/hosts override (idempotent: grep before append).
HOSTS_LINE="$BEDROCK_IP $BEDROCK_FQDN"
docker exec a14-kali bash -c "grep -Fq '$BEDROCK_FQDN' /etc/hosts || echo '$HOSTS_LINE' >> /etc/hosts"

# 5. Smoke test — invoke claude -p via Bedrock on the shard's primary
#    model. Fail fast if wiring is wrong. No secret material in output.
echo "kali bedrock shard hotfix: claude smoke test..."
if docker exec a14-kali bash -lc 'timeout 45 claude -p "reply with just: ok"' >/tmp/claude_smoke.out 2>&1; then
  head -c 200 /tmp/claude_smoke.out | tr -d '\n' | tr -c '[:print:]' ' '
  echo
  echo "kali bedrock shard hotfix: claude OK"
else
  rc=$?
  echo "kali bedrock shard hotfix: claude FAILED (rc=$rc)" >&2
  head -c 2000 /tmp/claude_smoke.out >&2
  exit 3
fi

echo "kali bedrock shard hotfix: complete"
"""


@dataclass(frozen=True)
class Target:
    instance_id: str
    vpc_id: str
    name: str
    user_id: str  # shifter:user_id tag value; may be "" if missing


# -----------------------------------------------------------------------------
# Discovery
# -----------------------------------------------------------------------------


def resolve_polaris_ami_id(ssm_client) -> str:
    try:
        resp = ssm_client.get_parameter(Name="/shifter/ami/polaris-vm")
    except ClientError as e:
        raise SystemExit(
            f"failed to read SSM /shifter/ami/polaris-vm: {e}. "
            "Pass --ami-id explicitly to skip the lookup."
        ) from e
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
                        user_id=tags.get("shifter:user_id", ""),
                    )
                )
    return targets


def hydrate_user_ids(ec2_client, targets: list[Target]) -> list[Target]:
    """For targets passed explicitly via --instance-ids we don't have
    tags yet; look them up in one DescribeInstances call."""
    missing = [t for t in targets if not t.user_id]
    if not missing:
        return targets

    paginator = ec2_client.get_paginator("describe_instances")
    hydrated: dict[str, Target] = {t.instance_id: t for t in targets}
    for page in paginator.paginate(InstanceIds=[t.instance_id for t in missing]):
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                tags = {t["Key"]: t["Value"] for t in (inst.get("Tags") or [])}
                iid = inst["InstanceId"]
                hydrated[iid] = Target(
                    instance_id=iid,
                    vpc_id=inst.get("VpcId", "?"),
                    name=tags.get("Name", hydrated[iid].name),
                    user_id=tags.get("shifter:user_id", ""),
                )
    return list(hydrated.values())


# -----------------------------------------------------------------------------
# Shard assignment + script rendering
# -----------------------------------------------------------------------------


def assign_shard(user_id: str, force: int | None, account_b_only: bool = False) -> int:
    if force is not None:
        return force
    if not user_id:
        raise ValueError("missing shifter:user_id tag (needed for shard assignment)")
    try:
        n = int(user_id)
    except ValueError as e:
        raise ValueError(f"shifter:user_id={user_id!r} is not an integer") from e
    if account_b_only:
        # Distribute across shards 4-7 (Account B × {us,global} × {4.5, 4.6}).
        return 4 + (n % 4)
    return n % len(SHARD_TABLE)


def render_script(shard_idx: int) -> str:
    account_id, model, fast_model = SHARD_TABLE[shard_idx]
    use_secret = "1" if account_id == ACCOUNT_B_ID else "0"
    # Substitute placeholders. We do simple string replace so the
    # template stays readable (no Python f-string braces to fight).
    return (
        INNER_SCRIPT_TEMPLATE
        .replace("__SHARD_IDX__", str(shard_idx))
        .replace("__ACCOUNT_ID__", account_id)
        .replace("__MODEL__", model)
        .replace("__FAST_MODEL__", fast_model)
        .replace("__USE_SECRET__", use_secret)
        .replace("__SECRET_ID__", ACCOUNT_B_SECRET_ID)
    )


# -----------------------------------------------------------------------------
# SSM send + wait
# -----------------------------------------------------------------------------


def ensure_imds_hop_limit(ec2_client, instance_ids: list[str]) -> dict[str, str]:
    """Bump IMDSv2 hop limit to 3 on each instance so containers on the
    Docker bridge can reach instance-profile creds via IMDS (Account A
    shards depend on this — without it IMDS token requests from inside
    a14-kali get dropped and Claude Code silently fails with no creds).

    Docker bridge adds one hop (host -> container). 2 is the proven
    minimum; 3 is one extra hop of insurance against future nested /
    overlay topology changes. Cost of the extra hop is negligible for
    ephemeral CTF ranges.

    Idempotent: re-setting to the current value is a no-op.

    Returns {instance_id: error_message} for instances that failed.
    """
    errors: dict[str, str] = {}
    for iid in instance_ids:
        try:
            ec2_client.modify_instance_metadata_options(
                InstanceId=iid,
                HttpPutResponseHopLimit=3,
                HttpTokens="required",
            )
        except ClientError as e:
            errors[iid] = str(e)
    return errors


def batched(seq: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def send_batch(
    ssm_client,
    instance_ids: list[str],
    script: str,
    max_concurrency: int,
    timeout_s: int,
    comment: str,
) -> str:
    resp = ssm_client.send_command(
        InstanceIds=instance_ids,
        DocumentName="AWS-RunShellScript",
        Comment=comment,
        Parameters={"commands": [script], "executionTimeout": [str(timeout_s)]},
        MaxConcurrency=str(max_concurrency),
        MaxErrors="3",
        TimeoutSeconds=timeout_s,
    )
    return resp["Command"]["CommandId"]


def wait_for_batch(ssm_client, command_id: str, poll_s: float = 5.0) -> dict[str, dict]:
    terminal = {"Success", "Cancelled", "TimedOut", "Failed"}
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
                    "StandardOutputContent": plugin_out[-1000:],
                    "StandardErrorContent": plugin_err[-1000:],
                }
        pending = [iid for iid, r in results.items() if r["Status"] not in terminal]
        if not pending and results:
            return results
        time.sleep(poll_s)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--profile", help="AWS named profile (Account A credentials). Default: AWS_PROFILE env or standard chain.")
    p.add_argument("--region", default="us-east-2")
    p.add_argument("--ami-id", help="Override AMI. Default: /shifter/ami/polaris-vm SSM param.")
    p.add_argument("--vpc-id", help="Restrict discovery to this VPC.")
    p.add_argument("--instance-ids", help="Comma-separated instance IDs. Skips AMI discovery.")
    p.add_argument(
        "--force-shard",
        type=int,
        help="Force all targets to this shard index (0..7). Testing only.",
    )
    p.add_argument(
        "--account-b-only",
        action="store_true",
        help="Route every target to Account B (shards 4-7). Use when Account A instance-profile path is unreliable.",
    )
    p.add_argument("--batch-size", type=int, default=50, help="IDs per SendCommand (SSM limit 50).")
    p.add_argument("--max-concurrency", type=int, default=10, help="Per-batch SSM concurrency.")
    p.add_argument("--timeout", type=int, default=180, help="Per-invocation timeout (seconds).")
    p.add_argument("--dry-run", action="store_true", help="Print shard plan and exit.")
    p.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size < 1 or args.batch_size > 50:
        print("--batch-size must be 1..50", file=sys.stderr)
        return 2
    if args.force_shard is not None and not (0 <= args.force_shard < len(SHARD_TABLE)):
        print(f"--force-shard must be 0..{len(SHARD_TABLE)-1}", file=sys.stderr)
        return 2

    session = boto3.Session(region_name=args.region, profile_name=args.profile)
    ec2 = session.client("ec2")
    ssm = session.client("ssm")

    # --- Resolve targets ---
    if args.instance_ids:
        ids = [s.strip() for s in args.instance_ids.split(",") if s.strip()]
        targets = [Target(instance_id=i, vpc_id="?", name="?", user_id="") for i in ids]
        if args.force_shard is None:
            # need user_id to shard; look up tags
            targets = hydrate_user_ids(ec2, targets)
    else:
        ami_id = args.ami_id or resolve_polaris_ami_id(ssm)
        print(f"discovering instances: ami_id={ami_id} vpc_id={args.vpc_id or '(any)'}")
        targets = discover_targets(ec2, ami_id, args.vpc_id)

    if not targets:
        print("no targets found.")
        return 0

    # --- Assign shards + group ---
    grouped: dict[int, list[Target]] = {}
    assign_errors: list[str] = []
    for t in targets:
        try:
            shard = assign_shard(t.user_id, args.force_shard, args.account_b_only)
        except ValueError as e:
            assign_errors.append(f"  {t.instance_id} name={t.name!r} user_id={t.user_id!r}: {e}")
            continue
        grouped.setdefault(shard, []).append(t)

    if assign_errors:
        print("shard-assignment errors (these targets will be skipped):")
        for line in assign_errors:
            print(line)

    total_assigned = sum(len(v) for v in grouped.values())
    print(f"\n{total_assigned} target(s) across {len(grouped)} shard(s):\n")
    for shard_idx in sorted(grouped):
        account_id, model, fast_model = SHARD_TABLE[shard_idx]
        acct = "A" if account_id == ACCOUNT_A_ID else "B"
        print(f"  shard {shard_idx} [{acct} {model}]  -> {len(grouped[shard_idx])} range(s)")
        for t in grouped[shard_idx][:5]:
            print(f"      {t.instance_id}  user_id={t.user_id}  name={t.name!r}")
        if len(grouped[shard_idx]) > 5:
            print(f"      ... +{len(grouped[shard_idx]) - 5} more")

    if args.dry_run:
        print("\n--dry-run: no commands sent.")
        return 0

    if not args.yes:
        ans = input(f"\napply kali bedrock shard to {total_assigned} range(s)? [yes/NO] ").strip()
        if ans.lower() not in {"yes", "y"}:
            print("aborted.")
            return 1

    # --- Raise IMDSv2 hop limit to 3 on every target before SSM ---
    # Account A shards use the EC2 instance profile via IMDS; Docker
    # bridge adds one hop, so the default EC2 hop_limit=1 blocks token
    # PUTs and Claude Code silently has no creds. 3 gives one extra
    # hop of insurance over the proven minimum (2). Idempotent.
    all_ids = [t.instance_id for shard in grouped.values() for t in shard]
    print(f"\nbumping IMDSv2 hop limit to 3 on {len(all_ids)} instance(s)...")
    imds_errors = ensure_imds_hop_limit(ec2, all_ids)
    if imds_errors:
        print(f"  {len(imds_errors)} instance(s) failed IMDS modify:")
        for iid, err in list(imds_errors.items())[:10]:
            print(f"    {iid}: {err}")
    else:
        print("  done.")

    # --- Send per-shard batches ---
    overall: dict[str, dict] = {}
    for shard_idx in sorted(grouped):
        shard_targets = grouped[shard_idx]
        script = render_script(shard_idx)
        instance_ids = [t.instance_id for t in shard_targets]
        for batch_num, chunk in enumerate(batched(instance_ids, args.batch_size), start=1):
            comment = f"kali bedrock shard {shard_idx} batch {batch_num}"
            print(f"\n{comment}: {len(chunk)} instance(s) -> SendCommand")
            try:
                command_id = send_batch(
                    ssm,
                    instance_ids=chunk,
                    script=script,
                    max_concurrency=args.max_concurrency,
                    timeout_s=args.timeout,
                    comment=comment,
                )
            except ClientError as e:
                print(f"  SendCommand failed: {e}", file=sys.stderr)
                for iid in chunk:
                    overall[iid] = {"Status": "SendFailed", "StatusDetails": str(e)}
                continue
            print(f"  command_id={command_id}, waiting...")
            results = wait_for_batch(ssm, command_id)
            overall.update(results)
            succ = sum(1 for r in results.values() if r["Status"] == "Success")
            fail = sum(1 for r in results.values() if r["Status"] != "Success")
            print(f"  shard {shard_idx} batch {batch_num} done: {succ} ok, {fail} non-success")

    # --- Summary ---
    print("\n=== summary ===")
    ok = [iid for iid, r in overall.items() if r["Status"] == "Success"]
    fail = {iid: r for iid, r in overall.items() if r["Status"] != "Success"}
    print(f"success: {len(ok)} / {len(overall)}")
    if fail:
        print("\nfailures:")
        for iid, r in fail.items():
            print(f"  {iid}: {r['Status']} / {r.get('StatusDetails','')}")
            err = (r.get("StandardErrorContent") or "").strip()
            if err:
                print(f"    stderr (last 1k): {err[-500:]}")

    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
