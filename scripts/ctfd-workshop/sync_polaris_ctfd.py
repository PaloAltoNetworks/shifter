#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from common import CtfdClient
from sync_polaris_ctfd_onboarding import (
    DEFAULT_ONBOARDING_PATH,
    DEFAULT_PAGES_DIR,
    ensure_flags,
    ensure_hints,
    find_by_key,
    load_json,
    load_pages,
    upsert_challenge,
    upsert_page,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHALLENGE_PATH = REPO_ROOT / "scenario-dev/polaris/build/ctfd-challenges.json"
SUPPORTED_FLAG_TYPES = {"static", "regex"}
STALE_CHALLENGE_NAMES = {
    "Mission 0 — Kali Warm-Up",
}
ORDERED_CHALLENGE_NAMES = [
    "Start Here — Kali Warm-Up",
    "Company Info",
    "Employee Directory",
    "Tech Stack Revealed",
    "Client Contracts",
    "DNS Reconnaissance",
    "Follow the Money",
    "Configuration Leak",
    "Project Hints",
    "Terminated Engineer",
    "Password Reuse",
    "Mundane File Share",
    "The Project",
    "Procurement Trail",
    "Hidden Group",
    "Lateral Movement",
    "Unreliable Guard",
    "Domain Admin",
    "The Analyst's Desk",
    "Old Defaults",
    "Compartment A",
    "Heavy Delivery",
    "MIDNIGHT-7",
    "What Git Remembers",
    "After Hours",
    "Balance Point",
    "Compartment B",
    "What's Built",
    "What Was Erased",
    "Full Run",
    "On Call",
    "Control Room",
    "Lights Out",
    "Underground Signals",
    "First Motion",
    "Walking Pattern",
    "Response Window",
    "Control Channel",
    "Full Override",
    "Q4 Risk Review",
    "Redacted Minutes",
    "Sanitized Diagram",
    "Press Drop",
    "Badge Clone",
    "Mailbox Rule",
    "Burner Visit",
    "Report the Mole",
    "Shipping Slot",
    "Approval Client",
    "Freeze Template",
    "Delivery Halt",
    "Maintenance Manual",
    "Diagnostic Channel",
    "Safe Mode Sequence",
    "Cold Shutdown",
]


class SyncError(RuntimeError):
    """Raised when the source manifest or live CTFd board fails validation."""


def validate_manifest(challenges: list[dict[str, Any]]) -> None:
    """Validate the merged source manifest before any CTFd mutation.

    A malformed manifest must fail loudly here, before stale-row deletion can
    remove event-critical live rows. Flag content is never echoed.
    """
    seen_ids: set[Any] = set()
    seen_names: set[str] = set()
    errors: list[str] = []

    for challenge in challenges:
        name = challenge.get("name")
        if not name:
            errors.append(
                f"challenge missing name (category={challenge.get('category')!r})"
            )
            continue
        if name in seen_names:
            errors.append(f"duplicate challenge name {name!r}")
        seen_names.add(name)

        if not challenge.get("category"):
            errors.append(f"challenge {name!r} missing category")

        manifest_id = challenge.get("id")
        if manifest_id is not None:
            if manifest_id in seen_ids:
                errors.append(f"duplicate manifest id {manifest_id!r} ({name})")
            seen_ids.add(manifest_id)

        flags = challenge.get("flags", [])
        if not flags:
            errors.append(f"challenge {name!r} has no flags — it would be unsubmittable")
        for flag in flags:
            flag_type = flag.get("type", "static")
            if flag_type not in SUPPORTED_FLAG_TYPES:
                errors.append(
                    f"challenge {name!r} has unsupported flag type {flag_type!r}"
                )
            if not flag.get("content"):
                errors.append(f"challenge {name!r} has a flag with empty content")

    if errors:
        raise SyncError("manifest validation failed:\n  " + "\n  ".join(errors))


def validate_live_challenge_names(existing_challenges: list[dict[str, Any]]) -> None:
    """Fail when the live board has duplicate challenge names.

    Sync is name-keyed, so a duplicate live name makes every upsert ambiguous.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for challenge in existing_challenges:
        name = challenge.get("name")
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    if duplicates:
        raise SyncError(
            "duplicate live CTFd challenge names make name-keyed sync unsafe: "
            + ", ".join(sorted(duplicates))
        )


def verify_challenge_rows(
    client: CtfdClient,
    *,
    challenges: list[dict[str, Any]],
    name_to_live_id: dict[str, int | None],
) -> None:
    """Read flag and hint rows back from CTFd after sync.

    Raises if a challenge with source flags (or hints) shows zero live rows —
    the exact regression that shipped 38/39 challenges unsubmittable.
    """
    failures: list[str] = []
    for challenge in challenges:
        name = challenge["name"]
        live_id = name_to_live_id.get(name)
        if live_id is None:
            failures.append(f"{name}: no live challenge id after sync")
            continue
        if challenge.get("flags"):
            rows = client.get(f"/challenges/{live_id}/flags").get("data", [])
            if not rows:
                failures.append(f"{name} (id {live_id}): 0 flag rows — unsubmittable")
        if challenge.get("hints"):
            rows = client.get(f"/challenges/{live_id}/hints").get("data", [])
            if not rows:
                failures.append(f"{name} (id {live_id}): 0 hint rows")
    if failures:
        raise SyncError("post-sync verification failed:\n  " + "\n  ".join(failures))


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


def get_all_items(
    client: CtfdClient,
    path: str,
    query: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    page = 1
    items: list[dict[str, Any]] = []
    base_query = dict(query or {})

    while True:
        payload = client.get(path, {**base_query, "page": page})
        data = payload.get("data", [])
        if not isinstance(data, list):
            return data
        items.extend(data)

        pagination = payload.get("meta", {}).get("pagination", {})
        total_pages = pagination.get("pages")
        if not total_pages or page >= total_pages:
            break
        page += 1

    return items


def build_manifest_id_to_name(challenges: list[dict[str, Any]]) -> dict[int, str]:
    return {challenge["id"]: challenge["name"] for challenge in challenges if "id" in challenge}


def sort_challenges(challenges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    name_order = {name: index for index, name in enumerate(ORDERED_CHALLENGE_NAMES, start=1)}
    fallback_index = len(name_order) + 1000
    return sorted(
        challenges,
        key=lambda challenge: (
            name_order.get(challenge["name"], fallback_index),
            challenge.get("category", ""),
            challenge.get("id", 0),
        ),
    )


def build_payload(
    *,
    challenge: dict[str, Any],
    position: int,
    requirements: dict[str, Any] | None = None,
    next_id: int | None = None,
) -> dict[str, Any]:
    payload = {
        "name": challenge["name"],
        "description": challenge["description"],
        "category": challenge["category"],
        "value": challenge["value"],
        "type": challenge.get("type", "standard"),
        "state": challenge.get("state", "visible"),
        "max_attempts": challenge.get("max_attempts", 0),
        "function": challenge.get("function", "static"),
        "logic": challenge.get("logic", "any"),
        "position": challenge.get("position", position),
        "requirements": requirements if requirements is not None else {"prerequisites": []},
    }
    if "connection_info" in challenge:
        payload["connection_info"] = challenge["connection_info"]
    if next_id is not None:
        payload["next_id"] = next_id
    return payload


def resolve_prerequisites(
    *,
    challenge: dict[str, Any],
    manifest_id_to_name: dict[int, str],
    name_to_live_id: dict[str, int | None],
) -> dict[str, Any]:
    raw_requirements = challenge.get("requirements", {})
    prerequisite_ids = []
    for manifest_id in raw_requirements.get("prerequisites", []):
        challenge_name = manifest_id_to_name.get(manifest_id)
        if not challenge_name:
            print(f"warn: prerequisite id {manifest_id!r} not found in manifest")
            continue
        live_id = name_to_live_id.get(challenge_name)
        if live_id is None:
            print(f"warn: prerequisite {challenge_name!r} has no live id yet")
            continue
        prerequisite_ids.append(live_id)

    return {"prerequisites": prerequisite_ids}


def ensure_tags(
    client: CtfdClient,
    *,
    challenge_id: int | None,
    challenge_name: str,
    tags: list[str],
    dry_run: bool,
) -> None:
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
        payload = build_payload(challenge=challenge, position=position)
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

        payload = build_payload(
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
