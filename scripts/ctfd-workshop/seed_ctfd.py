#!/usr/bin/env python3
"""Seed the standalone workshop CTFd with challenges, flags, and baseline config.

Challenge upsert and the generic ``find_by_key`` lookup live in
:mod:`ctfd_reconcile` and are shared with the Polaris sync paths. The
single-flag "keeper" semantics and the standalone-only solution helper
stay here because they're specific to this seeder (the Polaris board uses
``ctfd_reconcile.ensure_flags`` instead).
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from common import CtfdClient, load_event_config
from ctfd_reconcile import build_challenge_payload, find_by_key, upsert_challenge


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed the standalone workshop CTFd with challenges, flags, and baseline config."
    )
    parser.add_argument("--base-url", required=True, help="CTFd base URL, e.g. https://ctf.shifter.example.com")
    parser.add_argument(
        "--token",
        default=os.environ.get("CTFD_TOKEN"),
        help="CTFd admin API token. Defaults to CTFD_TOKEN.",
    )
    parser.add_argument(
        "--event-file",
        help="Path to the workshop event JSON. Defaults to scripts/ctfd-workshop/agentic_workshop.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without writing to CTFd.",
    )
    return parser.parse_args()


def _workshop_challenge_payload(
    *,
    challenge: dict[str, Any],
    category: str,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    """Workshop-shaped manifest -> CTFd payload (challenge_name key).

    The workshop manifest uses ``challenge_name`` where the Polaris manifest
    uses ``name``, and stores ``category`` at the top of the event JSON
    rather than per-challenge. ``build_challenge_payload`` expects both
    ``name`` and ``category`` on the challenge dict, so we bridge them
    here without forking the shared builder.
    """
    bridged = dict(challenge)
    bridged["name"] = challenge["challenge_name"]
    bridged["category"] = category
    bridged.setdefault("type", "standard")
    bridged.setdefault("state", "visible")
    bridged.setdefault("max_attempts", 0)
    bridged.setdefault("function", "static")
    bridged.setdefault("logic", "any")
    return build_challenge_payload(
        challenge=bridged,
        position=challenge["position"],
        requirements=requirements,
    )


def ensure_static_flag(
    client: CtfdClient,
    *,
    challenge_id: int,
    challenge_name: str,
    flag_value: str,
    dry_run: bool,
) -> None:
    """Keep one static flag per challenge.

    Differs from ``ctfd_reconcile.ensure_flags`` deliberately: this preserves
    the live flag row id by patching the first existing flag and deleting the
    rest, instead of delete-then-create when the content changes.
    """
    print(f"sync flag: {challenge_name}")
    if dry_run:
        return

    flags = client.get("/flags", {"challenge_id": challenge_id}).get("data", [])
    payload = {
        "challenge_id": challenge_id,
        "type": "static",
        "content": flag_value,
        "data": "",
    }

    keeper = None
    for flag in flags:
        if keeper is None:
            keeper = flag
            client.patch(f"/flags/{flag['id']}", payload)
        else:
            client.delete(f"/flags/{flag['id']}")

    if keeper is None:
        client.post("/flags", payload)


def ensure_hints(
    client: CtfdClient,
    *,
    challenge_id: int | None,
    challenge_name: str,
    hints: list[dict[str, Any]],
    dry_run: bool,
) -> None:
    """Workshop hint upsert. Does NOT delete stale hints (different from the
    Polaris ``ctfd_reconcile.ensure_hints`` behavior, which is keyed by
    ``title`` and removes anything not in the manifest)."""
    if not hints:
        return

    existing_hints: list[dict[str, Any]] = []
    if not dry_run and challenge_id is not None:
        existing_hints = client.get(f"/challenges/{challenge_id}/hints").get("data", [])

    for hint in hints:
        payload = {
            "challenge_id": challenge_id,
            "title": hint["title"],
            "content": hint["content"],
            "cost": hint.get("cost", 0),
            "requirements": hint.get("requirements", []),
        }
        existing = find_by_key(existing_hints, key="title", value=hint["title"])
        if existing:
            print(f"sync hint: {challenge_name} :: {hint['title']}")
            if not dry_run:
                client.patch(f"/hints/{existing['id']}", payload)
            continue

        print(f"create hint: {challenge_name} :: {hint['title']}")
        if not dry_run:
            response = client.post("/hints", payload)
            existing_hints.append(response["data"])


def ensure_solution(
    client: CtfdClient,
    *,
    existing_solutions: list[dict[str, Any]],
    challenge_id: int | None,
    challenge_name: str,
    solution: dict[str, Any] | None,
    dry_run: bool,
) -> None:
    if not solution:
        return

    print(f"sync solution: {challenge_name}")
    if dry_run or challenge_id is None:
        return

    payload = {
        "challenge_id": challenge_id,
        "content": solution["content"],
        "state": solution.get("state", "hidden"),
    }
    existing = find_by_key(existing_solutions, key="challenge_id", value=challenge_id)
    if existing:
        response = client.patch(f"/solutions/{existing['id']}", payload)
        updated = response["data"]
        for index, item in enumerate(existing_solutions):
            if item.get("id") == updated.get("id"):
                existing_solutions[index] = updated
                break
        return

    response = client.post("/solutions", payload)
    existing_solutions.append(response["data"])


def main() -> int:
    args = parse_args()
    if not args.token:
        raise SystemExit("missing --token and CTFD_TOKEN is not set")

    event = load_event_config(args.event_file)
    category = event["challenge_category"]
    client = CtfdClient(args.base_url, args.token)

    print("sync config")
    if not args.dry_run:
        client.patch("/configs", event["config"])

    existing_challenges = []
    existing_solutions: list[dict[str, Any]] = []
    if not args.dry_run:
        existing_challenges = client.get("/challenges", {"view": "admin"}).get("data", [])
        existing_solutions = client.get("/solutions").get("data", [])

    user_ids: dict[str, int | None] = {}

    for box in event["boxes"]:
        user_challenge = box["user"]
        payload = _workshop_challenge_payload(
            challenge=user_challenge,
            category=category,
            requirements={"prerequisites": []},
        )
        challenge = upsert_challenge(
            client,
            existing_challenges=existing_challenges,
            payload=payload,
            dry_run=args.dry_run,
        )
        user_ids[box["instance_name"]] = challenge.get("id")
        if challenge.get("id") is not None:
            ensure_static_flag(
                client,
                challenge_id=challenge["id"],
                challenge_name=payload["name"],
                flag_value=user_challenge["flag"],
                dry_run=args.dry_run,
            )
        ensure_hints(
            client,
            challenge_id=challenge.get("id"),
            challenge_name=payload["name"],
            hints=user_challenge.get("hints", []),
            dry_run=args.dry_run,
        )
        ensure_solution(
            client,
            existing_solutions=existing_solutions,
            challenge_id=challenge.get("id"),
            challenge_name=payload["name"],
            solution=user_challenge.get("solution"),
            dry_run=args.dry_run,
        )

    for box in event["boxes"]:
        root_challenge = box["root"]
        prereq_id = user_ids[box["instance_name"]]
        requirements = {"prerequisites": [prereq_id], "anonymize": False}
        payload = _workshop_challenge_payload(
            challenge=root_challenge,
            category=category,
            requirements=requirements,
        )
        challenge = upsert_challenge(
            client,
            existing_challenges=existing_challenges,
            payload=payload,
            dry_run=args.dry_run,
        )
        if challenge.get("id") is not None:
            ensure_static_flag(
                client,
                challenge_id=challenge["id"],
                challenge_name=payload["name"],
                flag_value=root_challenge["flag"],
                dry_run=args.dry_run,
            )
        ensure_hints(
            client,
            challenge_id=challenge.get("id"),
            challenge_name=payload["name"],
            hints=root_challenge.get("hints", []),
            dry_run=args.dry_run,
        )
        ensure_solution(
            client,
            existing_solutions=existing_solutions,
            challenge_id=challenge.get("id"),
            challenge_name=payload["name"],
            solution=root_challenge.get("solution"),
            dry_run=args.dry_run,
        )

    print("seed complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
