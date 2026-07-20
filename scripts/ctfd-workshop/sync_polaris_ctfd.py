#!/usr/bin/env python3
"""Sync the live Polaris CTFd board, onboarding challenge, and pages.

Generic CTFd reconciliation lives in :mod:`ctfd_reconcile`; Polaris-specific
ordering, validation, prereq resolution, and stale-name policy live in
:mod:`polaris_manifest`. This script wires the two layers together.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from common import CtfdClient
from ctfd_reconcile import (
    build_challenge_payload,
    ensure_flags,
    ensure_hints,
    get_all_items,
    load_json,
    load_pages,
    upsert_challenge,
    upsert_page,
)
from polaris_manifest import (
    STALE_CHALLENGE_NAMES,
    SyncError,
    build_manifest_id_to_name,
    resolve_prerequisites,
    sort_challenges,
    validate_live_challenge_names,
    validate_manifest,
    verify_challenge_rows,
)
from sync_polaris_ctfd_onboarding import DEFAULT_ONBOARDING_PATH, DEFAULT_PAGES_DIR

# Re-export so existing tests/imports keep working without churn.
from polaris_manifest import SUPPORTED_FLAG_TYPES, ORDERED_CHALLENGE_NAMES  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHALLENGE_PATH = REPO_ROOT / "scenario-dev/polaris/build/ctfd-challenges.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync the live Polaris CTFd board, onboarding challenge, and pages."
    )
    parser.add_argument("--base-url", required=True, help="CTFd base URL, e.g. https://polaris.example.com")
    parser.add_argument(
        "--token",
        default=os.environ.get("CTFD_TOKEN"),
        help="CTFd admin API token. Defaults to CTFD_TOKEN.",
    )
    parser.add_argument(
        "--challenge-file",
        default=str(DEFAULT_CHALLENGE_PATH),
        help="Path to the Polaris CTFd challenge manifest.",
    )
    parser.add_argument(
        "--onboarding-file",
        default=str(DEFAULT_ONBOARDING_PATH),
        help="Path to the Polaris onboarding JSON.",
    )
    parser.add_argument(
        "--pages-dir",
        default=str(DEFAULT_PAGES_DIR),
        help="Directory containing Polaris CTFd page Markdown files with front matter.",
    )
    parser.add_argument(
        "--skip-pages",
        action="store_true",
        help="Skip syncing the Polaris CTFd pages.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without writing to CTFd.",
    )
    return parser.parse_args()


def ensure_tags(
    client: CtfdClient,
    *,
    challenge_id: int | None,
    challenge_name: str,
    tags: list[str],
    dry_run: bool,
) -> None:
    """Reconcile tag rows for a challenge against the manifest's tag list.

    Stays in this script rather than ``ctfd_reconcile`` because the live tag
    surface uses a flat ``value`` key (not a row-keyed ``reconcile_rows``
    shape) and only the Polaris board uses it today.
    """
    if dry_run or challenge_id is None:
        for tag in tags:
            print(f"sync tag: {challenge_name} :: {tag}")
        return

    existing_tags = client.get(f"/challenges/{challenge_id}/tags").get("data", [])
    existing_by_value = {tag.get("value"): tag for tag in existing_tags}
    expected = set(tags)

    for tag in tags:
        if tag in existing_by_value:
            print(f"keep tag: {challenge_name} :: {tag}")
            continue
        print(f"create tag: {challenge_name} :: {tag}")
        client.post("/tags", {"challenge_id": challenge_id, "value": tag})

    for tag_value, tag in existing_by_value.items():
        if tag_value not in expected:
            print(f"delete stale tag: {challenge_name} :: {tag_value}")
            client.delete(f"/tags/{tag['id']}")


def sync_pages(
    client: CtfdClient,
    *,
    pages_dir: str,
    dry_run: bool,
) -> None:
    pages = load_pages(pages_dir)
    existing_pages: list[dict[str, Any]] = []
    if not dry_run:
        existing_pages = get_all_items(client, "/pages")

    for page in pages:
        upsert_page(
            client,
            existing_pages=existing_pages,
            page=page,
            dry_run=dry_run,
        )


def delete_stale_challenges(
    client: CtfdClient,
    *,
    existing_challenges: list[dict[str, Any]],
    dry_run: bool,
) -> list[dict[str, Any]]:
    remaining = []
    for challenge in existing_challenges:
        if challenge.get("name") not in STALE_CHALLENGE_NAMES:
            remaining.append(challenge)
            continue
        print(f"delete stale challenge: {challenge['name']}")
        if not dry_run:
            client.delete(f"/challenges/{challenge['id']}")
    return remaining


def sync_challenges(
    client: CtfdClient,
    *,
    challenges: list[dict[str, Any]],
    existing_challenges: list[dict[str, Any]],
    manifest_id_to_name: dict[int, str],
    dry_run: bool,
) -> dict[str, int | None]:
    """Upsert every challenge and reconcile its flags, hints, and tags.

    Returns the challenge-name to live-CTFd-id map for the verification pass.
    """
    synced_by_name: dict[str, dict[str, Any]] = {}

    for position, challenge in enumerate(challenges, start=1):
        # First pass: write empty prerequisites so unresolved manifest ids
        # never reach the live CTFd authorization gate. Pass two patches in
        # resolved live ids via resolve_prerequisites once every challenge
        # exists; if the sync aborts between the two passes, CTFd is left
        # with safe-by-default empty prereqs instead of stale manifest ids
        # that happen to collide with unrelated live challenge ids.
        payload = build_challenge_payload(
            challenge=challenge,
            position=position,
            requirements={"prerequisites": []},
        )
        synced = upsert_challenge(
            client,
            existing_challenges=existing_challenges,
            payload=payload,
            dry_run=dry_run,
        )
        synced_by_name[payload["name"]] = synced

    name_to_live_id = {name: synced.get("id") for name, synced in synced_by_name.items()}

    for position, challenge in enumerate(challenges, start=1):
        next_id = None
        next_name = challenge.get("next")
        if next_name:
            next_id = name_to_live_id.get(next_name)
            if next_id is None:
                print(f"warn: next challenge {next_name!r} not found; leaving next_id unset")

        payload = build_challenge_payload(
            challenge=challenge,
            position=position,
            requirements=resolve_prerequisites(
                challenge=challenge,
                manifest_id_to_name=manifest_id_to_name,
                name_to_live_id=name_to_live_id,
            ),
            next_id=next_id,
        )
        synced = upsert_challenge(
            client,
            existing_challenges=existing_challenges,
            payload=payload,
            dry_run=dry_run,
        )

        ensure_flags(
            client,
            challenge_id=synced.get("id"),
            challenge_name=payload["name"],
            flags=challenge.get("flags", []),
            dry_run=dry_run,
        )

        ensure_hints(
            client,
            challenge_id=synced.get("id"),
            challenge_name=payload["name"],
            hints=challenge.get("hints", []),
            dry_run=dry_run,
        )

        ensure_tags(
            client,
            challenge_id=synced.get("id"),
            challenge_name=payload["name"],
            tags=challenge.get("tags", []),
            dry_run=dry_run,
        )

    return name_to_live_id


def main() -> int:
    args = parse_args()
    if not args.token:
        raise SystemExit("missing --token and CTFD_TOKEN is not set")

    manifest = load_json(args.challenge_file)
    onboarding = load_json(args.onboarding_file)

    main_challenges = manifest.get("challenges", [])
    onboarding_challenges = onboarding.get("challenges", [])
    all_challenges = sort_challenges(main_challenges + onboarding_challenges)
    validate_manifest(all_challenges)
    manifest_id_to_name = build_manifest_id_to_name(all_challenges)

    client = CtfdClient(args.base_url, args.token)

    if not args.skip_pages:
        sync_pages(client, pages_dir=args.pages_dir, dry_run=args.dry_run)

    existing_challenges: list[dict[str, Any]] = []
    if not args.dry_run:
        existing_challenges = get_all_items(client, "/challenges", {"view": "admin"})
        validate_live_challenge_names(existing_challenges)
        existing_challenges = delete_stale_challenges(
            client,
            existing_challenges=existing_challenges,
            dry_run=args.dry_run,
        )

    name_to_live_id = sync_challenges(
        client,
        challenges=all_challenges,
        existing_challenges=existing_challenges,
        manifest_id_to_name=manifest_id_to_name,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        verify_challenge_rows(
            client,
            challenges=all_challenges,
            name_to_live_id=name_to_live_id,
        )

    print("Polaris CTFd sync complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SyncError as err:
        raise SystemExit(f"error: {err}") from err
