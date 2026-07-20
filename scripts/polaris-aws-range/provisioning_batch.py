"""Polaris provisioning batch state machine (issue #691).

Extracted from ``orchestrate_provisioning.py`` so ``run_one_batch`` and
its supporting helpers can be edited in isolation from the CLI entrypoint.

The portal-side Django-shell snippets (``FETCH_UNPROVISIONED_TEMPLATE``,
``TRIGGER_TEMPLATE``, ``STATUS_TEMPLATE``) live here too because they
travel with the orchestration logic that knows how to interpret their
output. They run through :mod:`common.PortalShellTransport` so the SSM
wrapper, base64 indirection, and JSON envelope parsing are not
re-implemented in this module.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from common import PortalShellTransport
from provisioning_state import (
    ParticipantOutcome,
    State,
    now_iso,
    save_state,
    write_status_doc,
)


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
# Portal Django-shell wrappers
# -----------------------------------------------------------------------------


def fetch_unprovisioned(
    transport: PortalShellTransport, event_id: str, limit: int, email_regex: str
) -> dict[str, Any]:
    script = (
        FETCH_UNPROVISIONED_TEMPLATE.replace("__EVENT_ID__", event_id)
        .replace("__LIMIT__", str(limit))
        .replace("__EMAIL_REGEX__", email_regex)
    )
    return transport.run_django(script, timeout_s=120)


def trigger_batch(
    transport: PortalShellTransport, participant_ids: list[str]
) -> dict[str, dict]:
    script = TRIGGER_TEMPLATE.replace("__PIDS__", json.dumps(participant_ids))
    return transport.run_django(script, timeout_s=300)


def check_range_status(
    transport: PortalShellTransport, range_ids: list[str]
) -> dict[str, dict]:
    if not range_ids:
        return {}
    script = STATUS_TEMPLATE.replace("__RIDS__", json.dumps(range_ids))
    return transport.run_django(script, timeout_s=120)


# -----------------------------------------------------------------------------
# Status logging
# -----------------------------------------------------------------------------


def log_line(msgs: list[str], line: str) -> None:
    ts = now_iso()
    formatted = f"{ts} {line}"
    print(formatted, flush=True)
    msgs.append(formatted)


# -----------------------------------------------------------------------------
# EC2 launch gate
# -----------------------------------------------------------------------------


def wait_for_ec2_launch(
    ec2_client,
    range_ids: list[str],
    log: list[str],
    timeout_s: int = 300,
    poll_interval_s: int = 20,
) -> dict[str, int]:
    """Wait until every range has at least 2 running/pending EC2 instances.

    Returns ``{range_id: instance_count}``. If timeout hits with some ranges
    short, returns what it has.
    """
    if not range_ids:
        return {}
    deadline = time.monotonic() + timeout_s
    counts: dict[str, int] = {}
    short: list[str] = []
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
        log_line(
            log,
            f"    EC2 gate: {sum(1 for n in counts.values() if n >= 2)}/{len(range_ids)} ranges have >=2 instances",
        )
        if not short:
            return counts
        time.sleep(poll_interval_s)
    log_line(log, f"    EC2 gate TIMEOUT: still short {len(short)} range(s): {short}")
    return counts


# -----------------------------------------------------------------------------
# Per-batch state transitions
# -----------------------------------------------------------------------------


def _register_initial_outcomes(state: State, batch: list[dict], batch_num: int) -> None:
    """Record per-participant ``triggered`` outcomes before the trigger call."""
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


def _record_trigger_results(
    state: State, batch: list[dict], trig: dict, current: list[str]
) -> list[str]:
    """Stamp trigger outcomes onto state; return the list of successful range ids."""
    range_ids: list[str] = []
    for p in batch:
        pid = p["participant_id"]
        tres = trig.get(pid, {})
        if "error" in tres:
            state.outcomes[pid].status = "trigger_error"
            state.outcomes[pid].error = tres["error"]
            state.outcomes[pid].finished_at = now_iso()
            log_line(current, f"  [TRIGGER FAIL] {p['email']}: {tres['error']}")
            continue
        rid = tres.get("range_instance_id")
        if rid is None:
            state.outcomes[pid].status = "trigger_error"
            state.outcomes[pid].error = "no range_instance_id returned"
            state.outcomes[pid].finished_at = now_iso()
            log_line(current, f"  [TRIGGER FAIL] {p['email']}: no range_id")
            continue
        state.outcomes[pid].range_instance_id = str(rid)
        range_ids.append(str(rid))
        log_line(current, f"  [TRIGGERED] {p['email']}: range={rid}")
    return range_ids


def _finalize_batch_outcomes(
    state: State, batch: list[dict], terminal: dict[str, str]
) -> tuple[int, int]:
    """Translate per-range terminal statuses into outcome counts (successes, failures)."""
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
    return successes, failures


# -----------------------------------------------------------------------------
# Wave-mode helpers
# -----------------------------------------------------------------------------


def _run_wave_ec2_mode(
    state: State,
    batch: list[dict],
    range_ids: list[str],
    args: argparse.Namespace,
    ec2,
    current: list[str],
    batch_num: int,
    *,
    state_path: Path,
    status_md_path: Path,
) -> tuple[int, int]:
    """Wave mode: trigger, wait for EC2 launch, return so the next wave can trigger."""
    log_line(
        current,
        f"wave mode: waiting up to {args.wave_gate_timeout}s for {len(range_ids)} ranges to launch EC2",
    )
    wait_for_ec2_launch(
        ec2,
        range_ids,
        current,
        timeout_s=args.wave_gate_timeout,
        poll_interval_s=args.wave_gate_poll,
    )
    successes = failures = 0
    for p in batch:
        o = state.outcomes[p["participant_id"]]
        if o.status == "trigger_error":
            failures += 1
            continue
        o.status = "triggered"
        o.finished_at = now_iso()
        successes += 1
    save_state(state, state_path)
    write_status_doc(state, current, status_md_path=status_md_path)
    log_line(
        current, f"wave {batch_num} EC2-gated: triggered={successes} trigger_errors={failures}"
    )
    return successes, failures


def _run_sleep_only_mode(
    state: State,
    batch: list[dict],
    args: argparse.Namespace,
    current: list[str],
    batch_num: int,
    *,
    state_path: Path,
    status_md_path: Path,
) -> tuple[int, int]:
    """Sleep-only mode: trust observed provisioning time, skip DB polling."""
    wait_s = args.sleep_only * 60
    log_line(current, f"sleep-only mode: waiting {args.sleep_only} min before next batch")
    time.sleep(wait_s)
    successes = failures = 0
    for p in batch:
        o = state.outcomes[p["participant_id"]]
        if o.status == "trigger_error":
            failures += 1
            continue
        o.status = "ready"
        o.finished_at = now_iso()
        successes += 1
    save_state(state, state_path)
    write_status_doc(state, current, status_md_path=status_md_path)
    log_line(
        current, f"batch {batch_num} assumed-ready: successes={successes} failures={failures}"
    )
    return successes, failures


def _wait_for_terminal(
    transport: PortalShellTransport,
    range_ids: list[str],
    args: argparse.Namespace,
    current: list[str],
) -> dict[str, str]:
    """Poll until every range reaches a terminal state or batch_timeout elapses."""
    log_line(current, f"waiting for {len(range_ids)} range(s) to reach terminal state...")
    deadline = time.monotonic() + args.batch_timeout * 60
    terminal: dict[str, str] = {}
    pending = list(range_ids)
    while pending and time.monotonic() < deadline:
        time.sleep(args.poll_interval)
        statuses = check_range_status(transport, pending)
        still_pending: list[str] = []
        for rid in pending:
            s = statuses.get(rid, {}).get("status", "?")
            if s in ("ready", "failed", "destroyed", "missing"):
                terminal[rid] = s
                log_line(current, f"  [{s.upper():8}] range={rid}")
            else:
                still_pending.append(rid)
        pending = still_pending
        if pending:
            log_line(current, f"  still pending: {len(pending)}")
    for rid in pending:
        terminal[rid] = "timeout"
    return terminal


# -----------------------------------------------------------------------------
# Public batch entrypoints
# -----------------------------------------------------------------------------


def run_one_batch(
    transport: PortalShellTransport,
    ec2,
    state: State,
    batch_num: int,
    args: argparse.Namespace,
    *,
    state_path: Path,
    status_md_path: Path,
) -> tuple[int, int]:
    """Trigger the next batch, wait for terminal state, record outcomes.

    Returns ``(successes, failures)`` for this batch.
    """
    current: list[str] = []
    log_line(current, f"=== batch {batch_num}: fetch up to {args.batch_size} unprovisioned ===")

    fetched = fetch_unprovisioned(transport, args.event_id, args.batch_size, args.email_regex)
    batch = fetched["batch"]
    log_line(
        current,
        f"unprovisioned remaining: {fetched['total_unprovisioned']}; batch size: {len(batch)}",
    )
    if not batch:
        return (0, 0)

    _register_initial_outcomes(state, batch, batch_num)
    save_state(state, state_path)
    write_status_doc(state, current, status_md_path=status_md_path)

    pids = [p["participant_id"] for p in batch]
    log_line(current, f"triggering provision for pids: {pids}")
    trig = trigger_batch(transport, pids)

    range_ids = _record_trigger_results(state, batch, trig, current)
    save_state(state, state_path)
    write_status_doc(state, current, status_md_path=status_md_path)

    if not range_ids:
        log_line(current, "no ranges triggered successfully; skipping wait")
        return (
            0,
            sum(1 for p in batch if state.outcomes[p["participant_id"]].status == "trigger_error"),
        )

    if args.wave_ec2_gate:
        return _run_wave_ec2_mode(
            state,
            batch,
            range_ids,
            args,
            ec2,
            current,
            batch_num,
            state_path=state_path,
            status_md_path=status_md_path,
        )

    if args.sleep_only > 0:
        return _run_sleep_only_mode(
            state,
            batch,
            args,
            current,
            batch_num,
            state_path=state_path,
            status_md_path=status_md_path,
        )

    terminal = _wait_for_terminal(transport, range_ids, args, current)
    successes, failures = _finalize_batch_outcomes(state, batch, terminal)
    save_state(state, state_path)
    write_status_doc(state, current, status_md_path=status_md_path)
    log_line(current, f"batch {batch_num} done: successes={successes} failures={failures}")
    return successes, failures


def _trigger_retry_and_collect_range_ids(
    state: State,
    retry_pids: list[str],
    transport: PortalShellTransport,
) -> list[str]:
    """Re-trigger provision for ``retry_pids``; mutate state and return ranges to wait on."""
    trig = trigger_batch(transport, retry_pids)
    range_ids: list[str] = []
    for pid in retry_pids:
        t = trig.get(pid, {})
        if "error" in t:
            state.outcomes[pid].status = "trigger_error"
            state.outcomes[pid].error = t["error"]
            state.outcomes[pid].finished_at = now_iso()
            continue
        rid = t.get("range_instance_id")
        if rid:
            state.outcomes[pid].range_instance_id = str(rid)
            range_ids.append(str(rid))
    return range_ids


def _finalize_retry_outcomes(
    state: State, retry_pids: list[str], terminal: dict[str, str]
) -> None:
    """Map terminal range statuses back onto the retry participants."""
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


def retry_failures(
    transport: PortalShellTransport,
    state: State,
    args: argparse.Namespace,
    *,
    state_path: Path,
    status_md_path: Path,
) -> None:
    """One retry pass for participants stuck at failed / trigger_error."""
    failed = [o for o in state.outcomes.values() if o.status in ("failed", "trigger_error")]
    if not failed:
        return

    current: list[str] = []
    log_line(current, f"=== retry pass: {len(failed)} participant(s) ===")

    # Before retry, the DB may already have range_instance_id set on some
    # participants (partial provision). Skip those by re-querying.
    fetched = fetch_unprovisioned(
        transport, args.event_id, limit=len(failed) + 5, email_regex=args.email_regex
    )
    still_unprovisioned = {p["participant_id"] for p in fetched["batch"]}
    retry_pids = [
        o.participant_id for o in failed if o.participant_id in still_unprovisioned
    ]
    log_line(current, f"retry pids (after DB re-check): {retry_pids}")

    if not retry_pids:
        log_line(current, "no retries needed; failures already recovered")
        write_status_doc(state, current, status_md_path=status_md_path)
        return

    for pid in retry_pids:
        state.outcomes[pid].status = "retrying"
        state.outcomes[pid].error = None
    save_state(state, state_path)
    write_status_doc(state, current, status_md_path=status_md_path)

    range_ids = _trigger_retry_and_collect_range_ids(state, retry_pids, transport)
    save_state(state, state_path)
    write_status_doc(state, current, status_md_path=status_md_path)

    if range_ids:
        log_line(current, f"waiting on {len(range_ids)} retry range(s)...")
        terminal = _wait_for_terminal(transport, range_ids, args, current)
        _finalize_retry_outcomes(state, retry_pids, terminal)

    save_state(state, state_path)
    write_status_doc(state, current, status_md_path=status_md_path)


__all__ = [
    "FETCH_UNPROVISIONED_TEMPLATE",
    "STATUS_TEMPLATE",
    "TRIGGER_TEMPLATE",
    "check_range_status",
    "fetch_unprovisioned",
    "log_line",
    "retry_failures",
    "run_one_batch",
    "trigger_batch",
    "wait_for_ec2_launch",
]
