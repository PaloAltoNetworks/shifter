#!/usr/bin/env python3
"""Sync the Polaris CTFd onboarding pages and the Start Here warm-up challenge.

Page and challenge upserts, row reconciliation, source-manifest readers,
and the generic ``ensure_flags`` / ``ensure_hints`` helpers all live in
:mod:`ctfd_reconcile`. This script is the thin orchestrator that loads
the onboarding manifest + pages and walks them through those helpers.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from common import CtfdClient
from ctfd_reconcile import (
    build_challenge_payload,
    ensure_flags,
    ensure_hints,
    find_by_key,
    load_json,
    load_pages,
    upsert_challenge,
    upsert_page,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ONBOARDING_PATH = REPO_ROOT / "scenario-dev/polaris/build/ctfd-onboarding.json"
DEFAULT_PAGES_DIR = REPO_ROOT / "scenario-dev/polaris/build/ctfd-pages"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync Polaris CTFd onboarding pages and the Start Here warm-up challenge."
    )
    parser.add_argument("--base-url", required=True, help="CTFd base URL, e.g. https://polaris.example.com")
    parser.add_argument(
        "--token",
        default=os.environ.get("CTFD_TOKEN"),
        help="CTFd admin API token. Defaults to CTFD_TOKEN.",
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
        "--dry-run",
        action="store_true",
        help="Print planned actions without writing to CTFd.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.token:
        raise SystemExit("missing --token and CTFD_TOKEN is not set")

    onboarding = load_json(args.onboarding_file)
    pages = load_pages(args.pages_dir)
    client = CtfdClient(args.base_url, args.token)

    existing_pages: list[dict] = []
    existing_challenges: list[dict] = []
    if not args.dry_run:
        existing_pages = client.get("/pages").get("data", [])
        existing_challenges = client.get("/challenges", {"view": "admin"}).get("data", [])

    for page in pages:
        upsert_page(
            client,
            existing_pages=existing_pages,
            page=page,
            dry_run=args.dry_run,
        )

    for index, challenge in enumerate(onboarding.get("challenges", []), start=1):
        next_id = None
        next_name = challenge.get("next")
        if next_name:
            next_challenge = find_by_key(existing_challenges, key="name", value=next_name)
            if next_challenge is not None:
                next_id = next_challenge.get("id")
            else:
                print(f"warn: next challenge {next_name!r} not found; leaving next_id unset")

        payload = build_challenge_payload(
            challenge=challenge,
            position=index,
            next_id=next_id,
        )
        synced = upsert_challenge(
            client,
            existing_challenges=existing_challenges,
            payload=payload,
            dry_run=args.dry_run,
        )
        ensure_flags(
            client,
            challenge_id=synced.get("id"),
            challenge_name=payload["name"],
            flags=challenge.get("flags", []),
            dry_run=args.dry_run,
        )
        ensure_hints(
            client,
            challenge_id=synced.get("id"),
            challenge_name=payload["name"],
            hints=challenge.get("hints", []),
            dry_run=args.dry_run,
        )

    print("Polaris onboarding sync complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
