"""Lambda: disable Claude on Polaris ranges whose operator cleared Full Override.

Runs on a 15-minute EventBridge schedule. Queries CTFd for solvers of the
final Bunker challenge (id 36 — Full Override). For each solver whose Kali
range has not yet been disabled, runs an SSM command to retire Claude Code
gracefully and tags the instance so we don't retry.

Safety invariants (cannot be overridden):
- Only challenge id 36 (hard-coded).
- Only instances with Name=kali AND shifter:user_id AND shifter:range_id tags.
- Only instances in 'running' state.
- Skip instances already tagged shifter:claude-disabled=true.
- Hard cap of 20 disables per Lambda invocation.
- Hard-coded denylist of infrastructure instance IDs (CTFd, portal, runners).
- KEEP_CLAUDE env var acts as an emergency allow-list of operator numbers that
  must never be touched.
- Tag is applied AFTER SSM success, not before — failed SSM → no tag → retry
  next tick.

Env vars:
    CTFD_URL                  https://polaris.example.com
    CTFD_TOKEN_SECRET_ID      polaris/claude-ops-token
    DRY_RUN                   "1" = print what WOULD happen, no changes
    KEEP_CLAUDE               comma-separated operator numbers to never disable
                              (e.g. "17,107"). Empty = no emergency allow-list.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.error
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# -----------------------------------------------------------------------------
# Hard-coded safety constants
# -----------------------------------------------------------------------------

REGION = "us-east-2"
CUTOFF_CHALLENGE_ID = 36          # Full Override — last Bunker flag
DISABLE_TAG_KEY = "shifter:claude-disabled"
MAX_DISABLES_PER_RUN = 20
SSM_TIMEOUT_SECONDS = 120

# Infrastructure instances — NEVER touch these even if some bug said to.
INFRA_INSTANCE_DENYLIST = frozenset({
    "i-08410b6d5d90beaf1",  # dev-portal-ctfd (CTFd host)
    "i-090a2ca9382c1b57b",  # dev-portal-ec2 (portal/shifter app)
    "i-09d5fa14bc9f314ba",
    "i-08b822184376ee282",
    "i-0ca850f4d7d3e34d9",
    "i-0aa67fe130a5120b7",
    "i-0dcc1b0f40c2f6c48",
    "i-01169dc56c6b49c6d",  # github runners
    "i-06a4b67517e046a9d",
    "i-01f8af88d13579acd",
})

EMAIL_RE = re.compile(r"^meetup\+(\d+)@bsidesottawa\.ca$", re.IGNORECASE)

# -----------------------------------------------------------------------------
# Payloads for the Kali-side disable action
# -----------------------------------------------------------------------------

CLAUDE_WRAPPER = """#!/bin/bash
cat <<'EOF'

========================================================
  OPERATION NORTHSTORM -- COMPLETE
========================================================

  You cleared the Bunker. Claude Code has been retired
  from your range. Your Kali box remains available --
  keep exploring.

  -- NORTHSTORM Command

========================================================

EOF
exit 0
"""

MOTD_BANNER = """
=========================================================
  NORTHSTORM COMMAND:  Bunker cleared. Claude retired.
=========================================================

"""

MOTD_MARKER = "NORTHSTORM COMMAND:  Bunker cleared"

# -----------------------------------------------------------------------------
# AWS clients (module-scope for Lambda container reuse)
# -----------------------------------------------------------------------------

_ec2 = boto3.client("ec2", region_name=REGION)
_ssm = boto3.client("ssm", region_name=REGION)
_sm = boto3.client("secretsmanager", region_name=REGION)


# -----------------------------------------------------------------------------
# CTFd helpers
# -----------------------------------------------------------------------------

def _ctfd_get(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_solvers(ctfd_url: str, token: str) -> list[dict]:
    """Return list of {user_id, name, email, op_num} for everyone who solved
    the cutoff challenge."""
    data = _ctfd_get(f"{ctfd_url}/api/v1/challenges/{CUTOFF_CHALLENGE_ID}/solves", token)
    solvers = []
    for entry in data.get("data", []):
        account_id = entry.get("account_id")
        if not account_id:
            continue
        # Fetch user to get email (name may have been renamed by operator)
        try:
            user = _ctfd_get(f"{ctfd_url}/api/v1/users/{account_id}", token)
            email = (user.get("data", {}).get("email") or "").lower()
        except Exception as e:
            logger.warning(f"could not fetch user {account_id}: {e}")
            continue
        m = EMAIL_RE.match(email)
        if not m:
            logger.info(f"skipping non-meetup email for challenge solve: {email}")
            continue
        solvers.append({
            "ctfd_user_id": account_id,
            "name": entry.get("name") or "",
            "email": email,
            "op_num": int(m.group(1)),
        })
    return solvers


# -----------------------------------------------------------------------------
# EC2 lookup
# -----------------------------------------------------------------------------

def find_kali_instance(op_num: int) -> dict | None:
    """Return {instance_id, tags, state} for this operator's Kali, or None."""
    resp = _ec2.describe_instances(Filters=[
        {"Name": "tag:Name", "Values": ["kali"]},
        {"Name": "tag:shifter:user_id", "Values": [str(op_num)]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ])
    for r in resp["Reservations"]:
        for i in r["Instances"]:
            iid = i["InstanceId"]
            if iid in INFRA_INSTANCE_DENYLIST:
                logger.error(f"SAFETY: op{op_num} resolved to denylisted instance {iid} — skipping")
                return None
            tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])}
            if "shifter:range_id" not in tags:
                logger.warning(f"op{op_num} instance {iid} missing shifter:range_id — skipping")
                continue
            return {
                "instance_id": iid,
                "tags": tags,
                "state": i["State"]["Name"],
            }
    return None


# -----------------------------------------------------------------------------
# SSM disable action
# -----------------------------------------------------------------------------

def build_disable_command() -> str:
    wrapper_b64 = base64.b64encode(CLAUDE_WRAPPER.encode()).decode()
    motd_b64 = base64.b64encode(MOTD_BANNER.encode()).decode()
    # The outer SSM script echoes base64 into docker exec to install files
    # inside the a14-kali container. All quoting is single-quoted or escaped.
    return f'''
set -euo pipefail

# 1) kill any running claude processes inside the kali container
docker exec a14-kali bash -c "pkill -f '^claude' 2>/dev/null || true"
docker exec a14-kali bash -c "pkill -f '/claude' 2>/dev/null || true"

# 2) install retired wrapper at /usr/local/bin/claude
echo "{wrapper_b64}" | base64 -d | docker exec -i a14-kali tee /usr/local/bin/claude >/dev/null
docker exec a14-kali chmod +x /usr/local/bin/claude

# 3) append MOTD banner if not already present
echo "{motd_b64}" | base64 -d > /tmp/motd_banner.txt
if docker exec a14-kali grep -q "{MOTD_MARKER}" /etc/motd 2>/dev/null; then
    echo "motd: already present"
else
    cat /tmp/motd_banner.txt | docker exec -i a14-kali tee -a /etc/motd >/dev/null
    echo "motd: appended"
fi
rm -f /tmp/motd_banner.txt

echo "claude-retired: ok"
'''


def disable_claude_on_instance(instance_id: str) -> dict:
    """Run the SSM disable command. Returns {status, stdout, stderr}."""
    cmd = build_disable_command()
    resp = _ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Comment="polaris end-of-game: retire claude",
        Parameters={"commands": [cmd], "executionTimeout": [str(SSM_TIMEOUT_SECONDS)]},
        TimeoutSeconds=SSM_TIMEOUT_SECONDS,
    )
    cid = resp["Command"]["CommandId"]
    # poll
    import time
    for _ in range(60):
        time.sleep(2)
        inv = _ssm.get_command_invocation(CommandId=cid, InstanceId=instance_id)
        if inv["Status"] in ("Success", "Failed", "TimedOut", "Cancelled"):
            break
    return {
        "status": inv["Status"],
        "stdout": (inv.get("StandardOutputContent") or "")[-500:],
        "stderr": (inv.get("StandardErrorContent") or "")[-500:],
    }


# -----------------------------------------------------------------------------
# Main handler
# -----------------------------------------------------------------------------

def handler(event, context):
    ctfd_url = os.environ.get("CTFD_URL", "https://polaris.example.com")
    secret_id = os.environ.get("CTFD_TOKEN_SECRET_ID", "polaris/claude-ops-token")
    dry_run = os.environ.get("DRY_RUN", "0") == "1"
    keep_claude_raw = (os.environ.get("KEEP_CLAUDE") or "").strip()
    keep_claude = {int(n) for n in keep_claude_raw.split(",") if n.strip().isdigit()}

    logger.info(f"start — dry_run={dry_run} keep_claude={sorted(keep_claude)}")

    # Fetch token
    token = _sm.get_secret_value(SecretId=secret_id)["SecretString"].strip()

    # Pull solvers
    solvers = fetch_solvers(ctfd_url, token)
    logger.info(f"{len(solvers)} operators have solved Full Override")

    if len(solvers) > MAX_DISABLES_PER_RUN:
        logger.error(f"SAFETY ABORT: {len(solvers)} > cap {MAX_DISABLES_PER_RUN} — not acting")
        return {"aborted": True, "reason": "cap_exceeded", "solver_count": len(solvers)}

    result = {
        "dry_run": dry_run,
        "solvers": len(solvers),
        "newly_disabled": [],
        "already_disabled": [],
        "skipped_keep_list": [],
        "no_instance": [],
        "errors": [],
    }

    disabled_this_run = 0

    for s in solvers:
        op = s["op_num"]
        # emergency allow-list
        if op in keep_claude:
            result["skipped_keep_list"].append(op)
            continue
        inst = find_kali_instance(op)
        if not inst:
            result["no_instance"].append(op)
            continue
        if inst["tags"].get(DISABLE_TAG_KEY) == "true":
            result["already_disabled"].append(op)
            continue

        if disabled_this_run >= MAX_DISABLES_PER_RUN:
            logger.error(f"SAFETY: hit per-run cap of {MAX_DISABLES_PER_RUN}, stopping")
            break

        if dry_run:
            logger.info(f"DRY_RUN would disable: op{op} instance={inst['instance_id']}")
            result["newly_disabled"].append({"op": op, "instance_id": inst["instance_id"], "mode": "dry_run"})
            continue

        # Execute
        try:
            r = disable_claude_on_instance(inst["instance_id"])
            if r["status"] != "Success":
                raise RuntimeError(f"SSM status={r['status']}, stderr={r['stderr']}")
            # Tag after SSM success
            _ec2.create_tags(
                Resources=[inst["instance_id"]],
                Tags=[{"Key": DISABLE_TAG_KEY, "Value": "true"}],
            )
            logger.info(f"disabled op{op} on {inst['instance_id']}")
            result["newly_disabled"].append({"op": op, "instance_id": inst["instance_id"], "mode": "executed"})
            disabled_this_run += 1
        except Exception as e:
            logger.exception(f"failed to disable op{op}")
            result["errors"].append({"op": op, "instance_id": inst.get("instance_id"), "error": str(e)})

    logger.info(f"summary: {json.dumps({k: v if not isinstance(v, list) else len(v) for k, v in result.items()})}")
    return result
