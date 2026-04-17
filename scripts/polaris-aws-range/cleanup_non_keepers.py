#!/usr/bin/env python3
"""Destroy Polaris event ranges EXCEPT for the 12 Lights-Out solvers.

Runs inside the portal Docker container on a dev-portal-ec2 host via
SSM — same pattern as polaris_ctf_attach.py and polaris_ctf_cleanup.py.

Policy:
  - KEEP the ranges of 12 operators whose emails are hard-coded below.
  - DESTROY every other range attached to the Polaris CTFEvent.

Default: dry-run (prints what WOULD be destroyed, makes no changes).
To actually destroy: pass --execute AND confirm by typing the event UUID.

Usage (from your workstation):

    python3 scripts/polaris-aws-range/cleanup_non_keepers.py                 # dry-run
    python3 scripts/polaris-aws-range/cleanup_non_keepers.py --execute       # real

The script fires an SSM command that runs the actual Django work inside
the portal container. See cleanup-plan.md for the policy rationale and
full keep/destroy lists.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time

import boto3

# -----------------------------------------------------------------------------
# Hard-coded safety config — DO NOT edit without cross-checking cleanup-plan.md
# -----------------------------------------------------------------------------

EVENT_ID = "fa1988b5-18fc-41d3-b3ff-ee97b0549546"

# The 12 operators who solved Mission 4 — Lights Out and earned Bunker access.
# Cross-reference: CTFd `Lights Out` challenge solves as of event-end snapshot
# 2026-04-16 23:22 EDT. Must match the list in cleanup-plan.md exactly.
KEEP_EMAILS = frozenset({
    "meetup+1@bsidesottawa.ca",
    "meetup+7@bsidesottawa.ca",
    "meetup+17@bsidesottawa.ca",
    "meetup+22@bsidesottawa.ca",
    "meetup+24@bsidesottawa.ca",
    "meetup+38@bsidesottawa.ca",
    "meetup+44@bsidesottawa.ca",
    "meetup+82@bsidesottawa.ca",
    "meetup+95@bsidesottawa.ca",
    "meetup+98@bsidesottawa.ca",
    "meetup+106@bsidesottawa.ca",
    "meetup+107@bsidesottawa.ca",
})

# Expected participant count range. If the DB has wildly different numbers
# than this, we abort rather than doing anything destructive.
EXPECTED_TOTAL_MIN = 90
EXPECTED_TOTAL_MAX = 130
EXPECTED_DESTROY_MAX = 110  # defense: never destroy more than this many

AWS_PROFILE = "panw-shifter-dev-workstation"
AWS_REGION = "us-east-2"
PORTAL_INSTANCE_TAG_NAME = "dev-portal-ec2"

# -----------------------------------------------------------------------------
# The Django-shell snippet that runs inside the portal container.
# -----------------------------------------------------------------------------

INNER_SCRIPT = r"""
import json, sys, traceback
from ctf.models import CTFEvent, CTFParticipant
from ctf.services.range import destroy_participant_range

EVENT_ID = "{event_id}"
KEEP_EMAILS = set({keep_emails_list!r})
DRY_RUN = {dry_run}

def emit(kind, **kw):
    sys.stdout.write("SHELL_EVENT|" + json.dumps({{"kind": kind, **kw}}, default=str) + "\n")
    sys.stdout.flush()

try:
    evt = CTFEvent.objects.get(pk=EVENT_ID)
    participants = list(CTFParticipant.objects.filter(event=evt))
    emit("start", event_name=evt.name, participant_count=len(participants), dry_run=DRY_RUN)

    # Safety: make sure every keep-list email appears in the participant set.
    db_emails = {{(p.email or '').lower() for p in participants}}
    missing = [e for e in KEEP_EMAILS if e.lower() not in db_emails]
    if missing:
        emit("abort", reason="keep-list email missing from DB", missing=missing)
        sys.exit(0)

    keepers = [p for p in participants if (p.email or '').lower() in KEEP_EMAILS]
    destroyers = [p for p in participants if (p.email or '').lower() not in KEEP_EMAILS]

    emit("plan", keepers=len(keepers), destroyers=len(destroyers))

    # Only destroy those with a range actually attached
    to_destroy = [p for p in destroyers if p.range_instance_id]
    emit("to_destroy", count=len(to_destroy))
    for p in to_destroy:
        emit("would_destroy", participant_id=str(p.id), email=p.email,
             range_instance_id=p.range_instance_id, range_status=p.range_status)

    if DRY_RUN:
        emit("done", destroyed=0, failed=0, dry_run=True)
        sys.exit(0)

    ok = fail = 0
    for p in to_destroy:
        try:
            destroy_participant_range(p.id)
            ok += 1
            emit("destroyed", participant_id=str(p.id), email=p.email)
        except Exception as e:
            fail += 1
            emit("destroy_failed", participant_id=str(p.id), email=p.email,
                 error=f"{{type(e).__name__}}: {{e}}")
    emit("done", destroyed=ok, failed=fail, dry_run=False)
except Exception:
    traceback.print_exc()
    emit("fatal", error=traceback.format_exc())
"""


def find_portal_instance(ec2) -> str:
    resp = ec2.describe_instances(Filters=[
        {"Name": "tag:Name", "Values": [PORTAL_INSTANCE_TAG_NAME]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ])
    for r in resp["Reservations"]:
        for i in r["Instances"]:
            return i["InstanceId"]
    raise RuntimeError(f"no running instance tagged Name={PORTAL_INSTANCE_TAG_NAME}")


def run_in_portal(ssm, instance_id: str, script: str) -> tuple[str, str]:
    """Ship the script into the portal container via SSM and return (stdout, stderr)."""
    py_b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    wrapper = rf"""
set -euo pipefail
echo "{py_b64}" | base64 -d > /tmp/cnk.py
sudo docker cp /tmp/cnk.py portal:/tmp/cnk.py
sudo docker exec portal bash -c 'while IFS= read -r -d "" kv; do export "$kv"; done < /proc/1/environ && cd /app && python manage.py shell < /tmp/cnk.py'
sudo docker exec portal rm -f /tmp/cnk.py || true
rm -f /tmp/cnk.py || true
"""
    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Comment="polaris cleanup non-keepers",
        Parameters={"commands": [wrapper], "executionTimeout": ["900"]},
        TimeoutSeconds=900,
    )
    cid = resp["Command"]["CommandId"]
    # poll
    for _ in range(180):
        time.sleep(5)
        inv = ssm.get_command_invocation(CommandId=cid, InstanceId=instance_id)
        if inv["Status"] in ("Success", "Failed", "Cancelled", "TimedOut"):
            break
    return inv.get("StandardOutputContent", ""), inv.get("StandardErrorContent", "")


def parse_events(stdout: str) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        if line.startswith("SHELL_EVENT|"):
            try:
                events.append(json.loads(line[len("SHELL_EVENT|"):]))
            except Exception:
                pass
    return events


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true",
                    help="Actually destroy ranges. WITHOUT THIS FLAG, the script is a pure dry-run.")
    ap.add_argument("--profile", default=AWS_PROFILE)
    ap.add_argument("--region", default=AWS_REGION)
    args = ap.parse_args()

    print(f"Policy: KEEP {len(KEEP_EMAILS)} operators, destroy the rest.")
    print("KEEP list:")
    for e in sorted(KEEP_EMAILS):
        print(f"  {e}")
    print()

    if args.execute:
        print("!!! --execute passed. This will DESTROY ranges. !!!")
        print(f"To confirm, type the event UUID ({EVENT_ID}):")
        entered = input("> ").strip()
        if entered != EVENT_ID:
            print("confirmation mismatch — aborting.")
            return 1
    else:
        print("Running in DRY-RUN mode (no changes will be made). Pass --execute to destroy.")

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    ec2 = session.client("ec2")
    ssm = session.client("ssm")
    portal = find_portal_instance(ec2)
    print(f"portal instance: {portal}")

    inner = INNER_SCRIPT.format(
        event_id=EVENT_ID,
        keep_emails_list=sorted(KEEP_EMAILS),
        dry_run=not args.execute,
    )
    stdout, stderr = run_in_portal(ssm, portal, inner)
    events = parse_events(stdout)

    # Summarize
    start = next((e for e in events if e["kind"] == "start"), None)
    plan = next((e for e in events if e["kind"] == "plan"), None)
    done = next((e for e in events if e["kind"] == "done"), None)
    abort = next((e for e in events if e["kind"] == "abort"), None)
    fatal = next((e for e in events if e["kind"] == "fatal"), None)

    if fatal:
        print("FATAL:")
        print(fatal.get("error", ""))
        return 2
    if abort:
        print(f"ABORTED: {abort.get('reason')}")
        print(json.dumps(abort, indent=2))
        return 3

    if start:
        print(f"event: {start['event_name']}")
        print(f"participants in DB: {start['participant_count']}")
        n = start["participant_count"]
        if not (EXPECTED_TOTAL_MIN <= n <= EXPECTED_TOTAL_MAX):
            print(f"SANITY ABORT: participant count {n} outside "
                  f"[{EXPECTED_TOTAL_MIN}, {EXPECTED_TOTAL_MAX}]")
            return 4
    if plan:
        print(f"  keepers found: {plan['keepers']}")
        print(f"  destroyers:    {plan['destroyers']}")
        if plan["keepers"] != len(KEEP_EMAILS):
            print(f"SANITY ABORT: found {plan['keepers']} keepers, expected {len(KEEP_EMAILS)}")
            return 5

    to_destroy = [e for e in events if e["kind"] == "would_destroy"]
    print(f"\nranges marked for destroy: {len(to_destroy)}")
    if len(to_destroy) > EXPECTED_DESTROY_MAX:
        print(f"SANITY ABORT: destroy count {len(to_destroy)} > {EXPECTED_DESTROY_MAX}")
        return 6
    for e in to_destroy:
        print(f"  {e['email']:<45s} participant={e['participant_id']} "
              f"range_instance={e['range_instance_id']} status={e['range_status']}")

    if args.execute:
        destroyed = [e for e in events if e["kind"] == "destroyed"]
        failed = [e for e in events if e["kind"] == "destroy_failed"]
        print(f"\ndestroyed: {len(destroyed)}")
        print(f"failed:    {len(failed)}")
        for f in failed:
            print(f"  FAIL {f['email']}  {f['error']}")
        print(f"\n{done}")
        return 0 if len(failed) == 0 else 7
    else:
        print(f"\nDRY-RUN complete. No changes made. Re-run with --execute to destroy.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
