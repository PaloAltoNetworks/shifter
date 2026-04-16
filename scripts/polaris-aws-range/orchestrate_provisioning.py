#!/usr/bin/env python3
"""BSides Ottawa polaris provisioning orchestrator.

Trigger / monitor / trigger loop for CTF participant ranges. Picks the
next N unprovisioned participants, fires ``cms.services.create_range``
for each via the portal container's Django shell, waits for all to
reach a terminal status (``ready`` or ``failed``), then does it again.

Two files are maintained under ``scripts/polaris-aws-range/``:

- ``provisioning_status.md`` — human-readable running log (one section
  per batch + a final summary + retry pass).
- ``provisioning_state.json`` — machine-readable state. Lets you resume
  after an interrupt (already-provisioned participants are identified
  from the live DB, so the json is mostly for diagnostics).

Abort policy (configurable):

- If any single batch has >= ``--batch-fail-threshold`` failures, halt.
- If cumulative failures >= ``--total-fail-threshold``, halt.
- Always print halted participant IDs so a human can review.

At the end (or on halt), the orchestrator does one retry pass on
failed participants and writes a summary.

Reads AWS creds from the usual boto3 chain; pass ``--profile`` for a
named profile. Uses SSM RunCommand against one portal EC2 instance to
execute Django shell code inside the portal docker container.

Usage::

    # Dry run (lists next batch, exits)
    python3 orchestrate_provisioning.py --profile panw-shifter-dev-workstation --dry-run

    # Run the real thing (batches of 10)
    python3 orchestrate_provisioning.py --profile panw-shifter-dev-workstation

    # Smaller batch + tighter abort threshold for testing
    python3 orchestrate_provisioning.py --profile panw-shifter-dev-workstation \\
        --batch-size 3 --batch-fail-threshold 2 --total-fail-threshold 4

Event ID is hard-coded to the BSides Ottawa event; override with
``--event-id`` if you need to rerun this for a different event.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

DEFAULT_EVENT_ID = "fa1988b5-18fc-41d3-b3ff-ee97b0549546"  # BSides Ottawa Polaris CTF
PORTAL_INSTANCE_TAG_NAME = "dev-portal-ec2"  # we pick any running one
CLUSTER = "dev-portal-pulumi"

STATE_DIR = Path(__file__).resolve().parent
STATUS_MD = STATE_DIR / "provisioning_status.md"
STATE_JSON = STATE_DIR / "provisioning_state.json"


# -----------------------------------------------------------------------------
# Inner Django shell scripts (run inside portal container via SSM)
# -----------------------------------------------------------------------------

# Fetch next N participants that don't have a range yet, plus a count.
FETCH_UNPROVISIONED_TEMPLATE = r"""
import json
from ctf.models import CTFParticipant

EVENT_ID = "__EVENT_ID__"
LIMIT = __LIMIT__
EMAIL_REGEX = r"__EMAIL_REGEX__"

qs = CTFParticipant.objects.filter(
    event_id=EVENT_ID,
    range_instance_id__isnull=True,
).select_related("user")
if EMAIL_REGEX:
    qs = qs.filter(email__regex=EMAIL_REGEX)
qs = qs.order_by("email")

total_unprovisioned = qs.count()
batch = list(qs[:LIMIT])

out = {
    "total_unprovisioned": total_unprovisioned,
    "batch": [
        {
            "participant_id": str(p.id),
            "email": p.email,
            "name": p.name,
            "user_id": p.user_id,
        }
        for p in batch
    ],
}
print("__JSON_START__")
print(json.dumps(out))
print("__JSON_END__")
"""


# Trigger provisioning for a specific list of participant IDs. Returns
# {participant_id: {"range_instance_id": "...", "status": "provisioning"}|{"error": "..."}}
TRIGGER_TEMPLATE = r"""
import json
from ctf.services.range import provision_participant_range

PARTICIPANT_IDS = __PIDS__

out = {}
for pid in PARTICIPANT_IDS:
    try:
        result = provision_participant_range(pid)
        out[pid] = {"range_instance_id": result.get("range_instance_id"), "status": result.get("status")}
    except Exception as e:
        out[pid] = {"error": f"{type(e).__name__}: {e}"}

print("__JSON_START__")
print(json.dumps(out))
print("__JSON_END__")
"""


# Poll Range status for a list of range instance IDs.
STATUS_TEMPLATE = r"""
import json
from engine.models import Range

RANGE_IDS = __RIDS__

out = {}
for rid in RANGE_IDS:
    try:
        r = Range.objects.get(pk=rid)
        out[str(rid)] = {"status": r.status, "name": r.name or ""}
    except Range.DoesNotExist:
        out[str(rid)] = {"status": "missing"}
    except Exception as e:
        out[str(rid)] = {"error": f"{type(e).__name__}: {e}"}

print("__JSON_START__")
print(json.dumps(out))
print("__JSON_END__")
"""


# -----------------------------------------------------------------------------
# SSM bridge
# -----------------------------------------------------------------------------

SSM_WRAPPER = r"""
set -euo pipefail
echo "$PY_B64" | base64 -d > /tmp/orch.py
sudo docker cp /tmp/orch.py portal:/tmp/orch.py
sudo docker exec portal bash -c '
  set -euo pipefail
  while IFS= read -r -d "" kv; do export "$kv"; done < /proc/1/environ
  cd /app
  python manage.py shell < /tmp/orch.py
'
"""


def run_django_shell(ssm_client, instance_id: str, python_script: str, timeout_s: int = 300) -> dict[str, Any]:
    """Run a Django-shell snippet inside the portal container.

    Parses a JSON block delimited by ``__JSON_START__`` / ``__JSON_END__``
    from stdout. Returns the parsed object or raises RuntimeError.
    """
    py_b64 = base64.b64encode(python_script.encode("utf-8")).decode("ascii")
    commands = [
        f"export PY_B64='{py_b64}'",
        SSM_WRAPPER,
    ]
    resp = ssm_client.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": ["\n".join(commands)], "executionTimeout": [str(timeout_s)]},
        TimeoutSeconds=timeout_s,
    )
    cmd_id = resp["Command"]["CommandId"]

    deadline = time.monotonic() + timeout_s + 30
    while time.monotonic() < deadline:
        time.sleep(3)
        try:
            r = ssm_client.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
        except ClientError as e:
            if "InvocationDoesNotExist" in str(e):
                continue
            raise
        status = r["Status"]
        if status in ("Success", "Failed", "TimedOut", "Cancelled"):
            stdout = r.get("StandardOutputContent", "")
            stderr = r.get("StandardErrorContent", "")
            if status != "Success":
                raise RuntimeError(
                    f"SSM command failed ({status}):\nstdout={stdout[-2000:]}\nstderr={stderr[-2000:]}"
                )
            # Parse JSON block
            start = stdout.find("__JSON_START__")
            end = stdout.find("__JSON_END__")
            if start == -1 or end == -1:
                raise RuntimeError(f"JSON markers missing in stdout: {stdout[-2000:]}")
            block = stdout[start + len("__JSON_START__") : end].strip()
            try:
                return json.loads(block)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"bad JSON in payload: {e}: {block[:500]}") from e
    raise RuntimeError(f"SSM command {cmd_id} did not finish within deadline")


# -----------------------------------------------------------------------------
# Status doc & state persistence
# -----------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ParticipantOutcome:
    participant_id: str
    email: str
    name: str
    range_instance_id: str | None = None
    status: str = "pending"  # pending|triggered|ready|failed|trigger_error
    error: str | None = None
    batch_num: int = 0
    started_at: str = ""
    finished_at: str = ""


@dataclass
class State:
    started_at: str = ""
    finished_at: str = ""
    total_participants: int = 0
    batches_completed: int = 0
    outcomes: dict[str, ParticipantOutcome] = field(default_factory=dict)
    halted: bool = False
    halt_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_participants": self.total_participants,
            "batches_completed": self.batches_completed,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "outcomes": {pid: vars(o) for pid, o in self.outcomes.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "State":
        s = cls(
            started_at=d.get("started_at", ""),
            finished_at=d.get("finished_at", ""),
            total_participants=d.get("total_participants", 0),
            batches_completed=d.get("batches_completed", 0),
            halted=d.get("halted", False),
            halt_reason=d.get("halt_reason", ""),
        )
        for pid, raw in (d.get("outcomes") or {}).items():
            s.outcomes[pid] = ParticipantOutcome(**raw)
        return s


def save_state(state: State) -> None:
    STATE_JSON.write_text(json.dumps(state.to_dict(), indent=2))


def load_state() -> State:
    if STATE_JSON.exists():
        try:
            return State.from_dict(json.loads(STATE_JSON.read_text()))
        except Exception:
            pass
    return State(started_at=now_iso())


def write_status_doc(state: State, current_batch_log: list[str]) -> None:
    lines: list[str] = []
    lines.append("# Polaris provisioning status")
    lines.append("")
    lines.append(f"- started: {state.started_at}")
    if state.finished_at:
        lines.append(f"- finished: {state.finished_at}")
    lines.append(f"- batches completed: {state.batches_completed}")
    lines.append(f"- participants tracked: {len(state.outcomes)}")
    if state.halted:
        lines.append(f"- **HALTED**: {state.halt_reason}")
    by_status: dict[str, int] = {}
    for o in state.outcomes.values():
        by_status[o.status] = by_status.get(o.status, 0) + 1
    if by_status:
        lines.append("")
        lines.append("## Outcome tally")
        for k, v in sorted(by_status.items()):
            lines.append(f"- {k}: {v}")
    # Failures table
    failures = [o for o in state.outcomes.values() if o.status in ("failed", "trigger_error")]
    if failures:
        lines.append("")
        lines.append("## Failures")
        lines.append("| batch | email | status | error |")
        lines.append("|---|---|---|---|")
        pipe = "\\|"
        for o in sorted(failures, key=lambda x: (x.batch_num, x.email)):
            err_cell = (o.error or "")[:200].replace("|", pipe)
            lines.append(f"| {o.batch_num} | {o.email} | {o.status} | {err_cell} |")
    if current_batch_log:
        lines.append("")
        lines.append("## Current / last batch log")
        lines.extend("- " + x for x in current_batch_log)
    STATUS_MD.write_text("\n".join(lines) + "\n")


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------


def find_portal_instance(ec2_client) -> str:
    """Pick any running instance tagged Name=dev-portal-ec2."""
    resp = ec2_client.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [PORTAL_INSTANCE_TAG_NAME]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    for reservation in resp["Reservations"]:
        for inst in reservation["Instances"]:
            return inst["InstanceId"]
    raise RuntimeError(f"no running instance tagged Name={PORTAL_INSTANCE_TAG_NAME}")


def fetch_unprovisioned(ssm, instance_id: str, event_id: str, limit: int, email_regex: str) -> dict[str, Any]:
    script = (
        FETCH_UNPROVISIONED_TEMPLATE.replace("__EVENT_ID__", event_id)
        .replace("__LIMIT__", str(limit))
        .replace("__EMAIL_REGEX__", email_regex)
    )
    return run_django_shell(ssm, instance_id, script, timeout_s=120)


def trigger_batch(ssm, instance_id: str, participant_ids: list[str]) -> dict[str, dict]:
    script = TRIGGER_TEMPLATE.replace("__PIDS__", json.dumps(participant_ids))
    return run_django_shell(ssm, instance_id, script, timeout_s=300)


def check_range_status(ssm, instance_id: str, range_ids: list[str]) -> dict[str, dict]:
    if not range_ids:
        return {}
    script = STATUS_TEMPLATE.replace("__RIDS__", json.dumps(range_ids))
    return run_django_shell(ssm, instance_id, script, timeout_s=120)


def log_line(msgs: list[str], line: str) -> None:
    ts = now_iso()
    formatted = f"{ts} {line}"
    print(formatted, flush=True)
    msgs.append(formatted)


def wait_for_ec2_launch(
    ec2_client, range_ids: list[str], log: list[str], timeout_s: int = 300, poll_interval_s: int = 20
) -> dict[str, int]:
    """Wait until every range has at least 2 running/pending EC2 instances.

    Returns {range_id: instance_count}. If timeout hits with some ranges
    short, returns what it has.
    """
    if not range_ids:
        return {}
    deadline = time.monotonic() + timeout_s
    counts: dict[str, int] = {}
    while time.monotonic() < deadline:
        counts = {rid: 0 for rid in range_ids}
        resp = ec2_client.describe_instances(
            Filters=[
                {"Name": "tag:shifter:range_id", "Values": range_ids},
                {"Name": "instance-state-name", "Values": ["pending", "running"]},
            ]
        )
        for r in resp["Reservations"]:
            for inst in r["Instances"]:
                for tag in inst.get("Tags") or []:
                    if tag["Key"] == "shifter:range_id":
                        counts[tag["Value"]] = counts.get(tag["Value"], 0) + 1
        short = [rid for rid, n in counts.items() if n < 2]
        log_line(log, f"    EC2 gate: {sum(1 for n in counts.values() if n >= 2)}/{len(range_ids)} ranges have >=2 instances")
        if not short:
            return counts
        time.sleep(poll_interval_s)
    log_line(log, f"    EC2 gate TIMEOUT: still short {len(short)} range(s): {short}")
    return counts


def run_one_batch(
    ssm, ec2, instance_id: str, state: State, batch_num: int, args: argparse.Namespace
) -> tuple[int, int]:
    """Trigger the next batch, wait for terminal state, record outcomes.

    Returns (successes, failures) for this batch.
    """
    current: list[str] = []
    log_line(current, f"=== batch {batch_num}: fetch up to {args.batch_size} unprovisioned ===")

    fetched = fetch_unprovisioned(ssm, instance_id, args.event_id, args.batch_size, args.email_regex)
    batch = fetched["batch"]
    remaining = fetched["total_unprovisioned"]
    log_line(current, f"unprovisioned remaining: {remaining}; batch size: {len(batch)}")

    if not batch:
        return (0, 0)

    # Register outcomes
    started = now_iso()
    for p in batch:
        pid = p["participant_id"]
        state.outcomes[pid] = ParticipantOutcome(
            participant_id=pid,
            email=p["email"],
            name=p["name"],
            status="triggered",
            batch_num=batch_num,
            started_at=started,
        )
    save_state(state)
    write_status_doc(state, current)

    # Trigger
    pids = [p["participant_id"] for p in batch]
    log_line(current, f"triggering provision for pids: {pids}")
    trig = trigger_batch(ssm, instance_id, pids)

    range_ids: list[str] = []
    for p in batch:
        pid = p["participant_id"]
        tres = trig.get(pid, {})
        if "error" in tres:
            state.outcomes[pid].status = "trigger_error"
            state.outcomes[pid].error = tres["error"]
            state.outcomes[pid].finished_at = now_iso()
            log_line(current, f"  [TRIGGER FAIL] {p['email']}: {tres['error']}")
        else:
            rid = tres.get("range_instance_id")
            if rid is None:
                state.outcomes[pid].status = "trigger_error"
                state.outcomes[pid].error = "no range_instance_id returned"
                state.outcomes[pid].finished_at = now_iso()
                log_line(current, f"  [TRIGGER FAIL] {p['email']}: no range_id")
            else:
                state.outcomes[pid].range_instance_id = str(rid)
                range_ids.append(str(rid))
                log_line(current, f"  [TRIGGERED] {p['email']}: range={rid}")
    save_state(state)
    write_status_doc(state, current)

    if not range_ids:
        log_line(current, "no ranges triggered successfully; skipping wait")
        return (0, sum(1 for p in batch if state.outcomes[p["participant_id"]].status == "trigger_error"))

    # Wave mode: trigger, wait until EC2 launched for this wave, then return so
    # the next wave can be triggered. The actual provisioning completion is
    # validated at end-of-run by a separate tool, not per-batch.
    if args.wave_ec2_gate:
        log_line(current, f"wave mode: waiting up to {args.wave_gate_timeout}s for {len(range_ids)} ranges to launch EC2")
        counts = wait_for_ec2_launch(
            ec2,
            range_ids,
            current,
            timeout_s=args.wave_gate_timeout,
            poll_interval_s=args.wave_gate_poll,
        )
        successes = 0
        failures = 0
        for p in batch:
            pid = p["participant_id"]
            o = state.outcomes[pid]
            if o.status == "trigger_error":
                failures += 1
                continue
            # Consider triggered; final verification happens at end of run
            o.status = "triggered"
            o.finished_at = now_iso()
            successes += 1
        save_state(state)
        write_status_doc(state, current)
        log_line(current, f"wave {batch_num} EC2-gated: triggered={successes} trigger_errors={failures}")
        return (successes, failures)

    # Sleep-only mode: trust the observed provisioning time, skip DB polling
    if args.sleep_only > 0:
        wait_s = args.sleep_only * 60
        log_line(current, f"sleep-only mode: waiting {args.sleep_only} min before next batch")
        time.sleep(wait_s)
        successes = 0
        failures = 0
        for p in batch:
            pid = p["participant_id"]
            o = state.outcomes[pid]
            if o.status == "trigger_error":
                failures += 1
                continue
            # Treat as ready (will be verified end-to-end at summary)
            o.status = "ready"
            o.finished_at = now_iso()
            successes += 1
        save_state(state)
        write_status_doc(state, current)
        log_line(current, f"batch {batch_num} assumed-ready: successes={successes} failures={failures}")
        return (successes, failures)

    # Wait for terminal
    log_line(current, f"waiting for {len(range_ids)} range(s) to reach terminal state...")
    deadline = time.monotonic() + args.batch_timeout * 60
    terminal: dict[str, str] = {}
    while range_ids and time.monotonic() < deadline:
        time.sleep(args.poll_interval)
        statuses = check_range_status(ssm, instance_id, range_ids)
        still_pending: list[str] = []
        for rid in range_ids:
            s = statuses.get(rid, {}).get("status", "?")
            if s in ("ready", "failed", "destroyed", "missing"):
                terminal[rid] = s
                log_line(current, f"  [{s.upper():8}] range={rid}")
            else:
                still_pending.append(rid)
        range_ids = still_pending
        if range_ids:
            log_line(current, f"  still pending: {len(range_ids)}")

    # Any remaining are timeouts
    for rid in range_ids:
        terminal[rid] = "timeout"

    # Update outcomes based on range status
    successes = failures = 0
    for p in batch:
        pid = p["participant_id"]
        o = state.outcomes[pid]
        if o.status == "trigger_error":
            failures += 1
            continue
        rid = o.range_instance_id
        if rid is None:
            continue
        s = terminal.get(rid, "unknown")
        o.finished_at = now_iso()
        if s == "ready":
            o.status = "ready"
            successes += 1
        else:
            o.status = "failed"
            o.error = f"terminal range status={s}"
            failures += 1
    save_state(state)
    write_status_doc(state, current)
    log_line(current, f"batch {batch_num} done: successes={successes} failures={failures}")
    return (successes, failures)


def retry_failures(
    ssm, ec2, instance_id: str, state: State, args: argparse.Namespace
) -> None:
    """One retry pass for participants stuck at failed / trigger_error."""
    failed = [o for o in state.outcomes.values() if o.status in ("failed", "trigger_error")]
    if not failed:
        return

    current: list[str] = []
    log_line(current, f"=== retry pass: {len(failed)} participant(s) ===")

    # Before retry, the DB may already have range_instance_id set on some
    # participants (partial provision). Skip those by re-querying.
    fetched = fetch_unprovisioned(ssm, instance_id, args.event_id, limit=len(failed) + 5, email_regex=args.email_regex)
    still_unprovisioned = {p["participant_id"] for p in fetched["batch"]}
    retry_pids = [o.participant_id for o in failed if o.participant_id in still_unprovisioned]
    log_line(current, f"retry pids (after DB re-check): {retry_pids}")

    if not retry_pids:
        log_line(current, "no retries needed; failures already recovered")
        write_status_doc(state, current)
        return

    # Mark retrying
    for pid in retry_pids:
        state.outcomes[pid].status = "retrying"
        state.outcomes[pid].error = None
    save_state(state)
    write_status_doc(state, current)

    # Trigger + wait
    trig = trigger_batch(ssm, instance_id, retry_pids)
    range_ids: list[str] = []
    for pid in retry_pids:
        t = trig.get(pid, {})
        if "error" in t:
            state.outcomes[pid].status = "trigger_error"
            state.outcomes[pid].error = t["error"]
            state.outcomes[pid].finished_at = now_iso()
        else:
            rid = t.get("range_instance_id")
            if rid:
                state.outcomes[pid].range_instance_id = str(rid)
                range_ids.append(str(rid))
    save_state(state)
    write_status_doc(state, current)

    if range_ids:
        log_line(current, f"waiting on {len(range_ids)} retry range(s)...")
        deadline = time.monotonic() + args.batch_timeout * 60
        terminal: dict[str, str] = {}
        while range_ids and time.monotonic() < deadline:
            time.sleep(args.poll_interval)
            statuses = check_range_status(ssm, instance_id, range_ids)
            still = []
            for rid in range_ids:
                s = statuses.get(rid, {}).get("status", "?")
                if s in ("ready", "failed", "destroyed", "missing"):
                    terminal[rid] = s
                    log_line(current, f"  [{s.upper():8}] range={rid}")
                else:
                    still.append(rid)
            range_ids = still
        for rid in range_ids:
            terminal[rid] = "timeout"

        for pid in retry_pids:
            o = state.outcomes[pid]
            if o.status == "trigger_error":
                continue
            rid = o.range_instance_id
            s = terminal.get(rid, "unknown")
            o.finished_at = now_iso()
            if s == "ready":
                o.status = "ready"
            else:
                o.status = "failed"
                o.error = f"retry terminal status={s}"

    save_state(state)
    write_status_doc(state, current)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", help="AWS profile (Account A / portal). Default: boto3 chain.")
    p.add_argument("--region", default="us-east-2")
    p.add_argument("--event-id", default=DEFAULT_EVENT_ID)
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--batch-fail-threshold", type=int, default=4, help="Halt if single batch has this many failures.")
    p.add_argument("--total-fail-threshold", type=int, default=10, help="Halt if cumulative failures reach this.")
    p.add_argument("--batch-timeout", type=int, default=60, help="Per-batch max wait for terminal state (minutes).")
    p.add_argument("--poll-interval", type=int, default=60, help="Seconds between Range.status polls.")
    p.add_argument(
        "--sleep-only",
        type=int,
        default=0,
        help="If >0, skip Range.status polling and simply sleep this many minutes after triggering each batch before moving on. More reliable when Range.status updates lag behind actual provisioning completion. Verification happens at the end via a separate tool.",
    )
    p.add_argument(
        "--wave-ec2-gate",
        action="store_true",
        help="After triggering a wave, move to the next wave as soon as each range has EC2 instances launched (pending/running). Pipelines waves so many can provision concurrently. Overrides --sleep-only.",
    )
    p.add_argument("--wave-gate-timeout", type=int, default=300, help="Seconds to wait for EC2 launch per wave.")
    p.add_argument("--wave-gate-poll", type=int, default=20, help="Seconds between EC2 gate polls.")
    p.add_argument("--final-wait", type=int, default=25, help="Minutes to sleep after triggering the last wave before finishing.")
    p.add_argument("--max-batches", type=int, default=20, help="Hard cap on batches (safety).")
    p.add_argument(
        "--email-regex",
        default=r"^meetup\+\d+@bsidesottawa\.ca$",
        help="Only consider CTF participants whose email matches this regex. Empty = no filter.",
    )
    p.add_argument("--dry-run", action="store_true", help="Show what the first batch would be and exit.")
    p.add_argument("--yes", action="store_true", help="Skip the pre-flight confirmation prompt.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    ec2 = session.client("ec2")
    ssm = session.client("ssm")

    instance_id = find_portal_instance(ec2)
    print(f"portal instance: {instance_id}")

    # Dry run: fetch + show
    first = fetch_unprovisioned(ssm, instance_id, args.event_id, args.batch_size, args.email_regex)
    print(f"unprovisioned: {first['total_unprovisioned']} total; next batch of {len(first['batch'])}:")
    for p in first["batch"]:
        print(f"  {p['email']}  (participant_id={p['participant_id']}, user_id={p['user_id']})")

    if args.dry_run:
        return 0
    if first["total_unprovisioned"] == 0:
        print("nothing to do.")
        return 0

    if not args.yes:
        ans = input(f"\nproceed with batches of {args.batch_size} (abort at {args.batch_fail_threshold}/batch or {args.total_fail_threshold} total)? [yes/NO] ").strip()
        if ans.lower() not in ("yes", "y"):
            print("aborted.")
            return 1

    state = load_state()
    if not state.started_at:
        state.started_at = now_iso()
    state.total_participants = first["total_unprovisioned"] + sum(
        1 for o in state.outcomes.values() if o.status == "ready"
    )
    save_state(state)

    total_failures = sum(1 for o in state.outcomes.values() if o.status in ("failed", "trigger_error"))
    for batch_num in range(state.batches_completed + 1, args.max_batches + 1):
        succ, fail = run_one_batch(ssm, ec2, instance_id, state, batch_num, args)
        state.batches_completed = batch_num
        total_failures += fail
        save_state(state)

        if succ == 0 and fail == 0:
            # nothing to do
            break

        if fail >= args.batch_fail_threshold:
            state.halted = True
            state.halt_reason = f"batch {batch_num} had {fail} failures (threshold {args.batch_fail_threshold})"
            break
        if total_failures >= args.total_fail_threshold:
            state.halted = True
            state.halt_reason = f"cumulative failures {total_failures} reached threshold {args.total_fail_threshold}"
            break

    # In wave/EC2-gate mode, the last wave just finished EC2 launch. Give
    # everything time to complete docker-compose bootstrap before wrap up.
    if args.wave_ec2_gate and args.final_wait > 0 and not state.halted:
        print(f"final wait: {args.final_wait} min to let last wave finish provisioning...")
        time.sleep(args.final_wait * 60)

    # Retry pass (even if halted, give them one more chance)
    retry_failures(ssm, ec2, instance_id, state, args)

    state.finished_at = now_iso()
    save_state(state)
    write_status_doc(state, [])
    print(f"DONE. halted={state.halted} reason={state.halt_reason!r}")
    print(f"state: {STATE_JSON}")
    print(f"status: {STATUS_MD}")
    return 0 if not state.halted else 2


if __name__ == "__main__":
    sys.exit(main())
