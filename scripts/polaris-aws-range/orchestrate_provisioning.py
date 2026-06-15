#!/usr/bin/env python3
"""BSides Ottawa polaris provisioning orchestrator.

Trigger / monitor / trigger loop for CTF participant ranges. Picks the
next N unprovisioned participants, fires ``ctf.services.range.provision_participant_range``
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

The state model lives in :mod:`provisioning_state`; the batch state
machine and Django-shell snippets live in :mod:`provisioning_batch`;
the AWS / SSM transport lives in :mod:`common`. This entrypoint just
wires the CLI, picks the next batch, and runs the loop.

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
import sys
import time
from pathlib import Path

from common import PolarisAwsContext, PortalShellTransport, SsmExecutor, find_portal_instance
from provisioning_batch import (
    fetch_unprovisioned,
    retry_failures,
    run_one_batch,
)
from provisioning_state import State, load_state, now_iso, save_state, write_status_doc

DEFAULT_EVENT_ID = "fa1988b5-18fc-41d3-b3ff-ee97b0549546"  # BSides Ottawa Polaris CTF

STATE_DIR = Path(__file__).resolve().parent
STATUS_MD = STATE_DIR / "provisioning_status.md"
STATE_JSON = STATE_DIR / "provisioning_state.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--profile", help="AWS profile (Account A / portal). Default: boto3 chain.")
    p.add_argument("--region", default="us-east-2")
    p.add_argument("--event-id", default=DEFAULT_EVENT_ID)
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument(
        "--batch-fail-threshold",
        type=int,
        default=4,
        help="Halt if single batch has this many failures.",
    )
    p.add_argument(
        "--total-fail-threshold",
        type=int,
        default=10,
        help="Halt if cumulative failures reach this.",
    )
    p.add_argument(
        "--batch-timeout",
        type=int,
        default=60,
        help="Per-batch max wait for terminal state (minutes).",
    )
    p.add_argument(
        "--poll-interval", type=int, default=60, help="Seconds between Range.status polls."
    )
    p.add_argument(
        "--sleep-only",
        type=int,
        default=0,
        help=(
            "If >0, skip Range.status polling and simply sleep this many minutes after triggering "
            "each batch before moving on. More reliable when Range.status updates lag behind actual "
            "provisioning completion. Verification happens at the end via a separate tool."
        ),
    )
    p.add_argument(
        "--wave-ec2-gate",
        action="store_true",
        help=(
            "After triggering a wave, move to the next wave as soon as each range has EC2 instances "
            "launched (pending/running). Pipelines waves so many can provision concurrently. "
            "Overrides --sleep-only."
        ),
    )
    p.add_argument(
        "--wave-gate-timeout",
        type=int,
        default=300,
        help="Seconds to wait for EC2 launch per wave.",
    )
    p.add_argument(
        "--wave-gate-poll", type=int, default=20, help="Seconds between EC2 gate polls."
    )
    p.add_argument(
        "--final-wait",
        type=int,
        default=25,
        help="Minutes to sleep after triggering the last wave before finishing.",
    )
    p.add_argument(
        "--max-batches", type=int, default=20, help="Hard cap on batches (safety)."
    )
    p.add_argument(
        "--email-regex",
        default=r"^meetup\+\d+@bsidesottawa\.ca$",
        help="Only consider CTF participants whose email matches this regex. Empty = no filter.",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Show what the first batch would be and exit."
    )
    p.add_argument(
        "--yes", action="store_true", help="Skip the pre-flight confirmation prompt."
    )
    return p.parse_args()


def _run_batch_loop(
    transport: PortalShellTransport,
    ec2,
    state: State,
    args: argparse.Namespace,
) -> int:
    """Run batches until the queue empties, a threshold trips, or max_batches hits."""
    total_failures = sum(
        1 for o in state.outcomes.values() if o.status in ("failed", "trigger_error")
    )
    for batch_num in range(state.batches_completed + 1, args.max_batches + 1):
        succ, fail = run_one_batch(
            transport,
            ec2,
            state,
            batch_num,
            args,
            state_path=STATE_JSON,
            status_md_path=STATUS_MD,
        )
        state.batches_completed = batch_num
        total_failures += fail
        save_state(state, STATE_JSON)

        if succ == 0 and fail == 0:
            break
        if fail >= args.batch_fail_threshold:
            state.halted = True
            state.halt_reason = (
                f"batch {batch_num} had {fail} failures (threshold {args.batch_fail_threshold})"
            )
            break
        if total_failures >= args.total_fail_threshold:
            state.halted = True
            state.halt_reason = (
                f"cumulative failures {total_failures} reached threshold "
                f"{args.total_fail_threshold}"
            )
            break
    return total_failures


def main() -> int:
    args = parse_args()
    ctx = PolarisAwsContext(profile=args.profile, region=args.region)
    ec2 = ctx.ec2()
    executor = SsmExecutor(ctx.ssm())

    instance_id = find_portal_instance(ec2)
    print(f"portal instance: {instance_id}")
    transport = PortalShellTransport(executor=executor, portal_instance_id=instance_id, tmp_name="orch")

    first = fetch_unprovisioned(transport, args.event_id, args.batch_size, args.email_regex)
    print(
        f"unprovisioned: {first['total_unprovisioned']} total; "
        f"next batch of {len(first['batch'])}:"
    )
    for p in first["batch"]:
        print(f"  {p['email']}  (participant_id={p['participant_id']}, user_id={p['user_id']})")

    if args.dry_run:
        return 0
    if first["total_unprovisioned"] == 0:
        print("nothing to do.")
        return 0

    if not args.yes:
        ans = input(
            f"\nproceed with batches of {args.batch_size} (abort at "
            f"{args.batch_fail_threshold}/batch or {args.total_fail_threshold} total)? [yes/NO] "
        ).strip()
        if ans.lower() not in ("yes", "y"):
            print("aborted.")
            return 1

    state = load_state(STATE_JSON)
    if not state.started_at:
        state.started_at = now_iso()
    state.total_participants = first["total_unprovisioned"] + sum(
        1 for o in state.outcomes.values() if o.status == "ready"
    )
    save_state(state, STATE_JSON)

    _run_batch_loop(transport, ec2, state, args)

    if args.wave_ec2_gate and args.final_wait > 0 and not state.halted:
        print(f"final wait: {args.final_wait} min to let last wave finish provisioning...")
        time.sleep(args.final_wait * 60)

    retry_failures(
        transport,
        state,
        args,
        state_path=STATE_JSON,
        status_md_path=STATUS_MD,
    )

    state.finished_at = now_iso()
    save_state(state, STATE_JSON)
    write_status_doc(state, [], status_md_path=STATUS_MD)
    print(f"DONE. halted={state.halted} reason={state.halt_reason!r}")
    print(f"state: {STATE_JSON}")
    print(f"status: {STATUS_MD}")
    return 0 if not state.halted else 2


if __name__ == "__main__":
    sys.exit(main())
