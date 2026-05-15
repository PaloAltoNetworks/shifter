#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from common import CtfdClient


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


def load_json(path: str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_scalar(raw: str) -> Any:
    text = raw.strip()
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    return text


def parse_page(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} is missing front matter")

    meta: dict[str, Any] = {}
    index = 1
    while index < len(lines):
        line = lines[index]
        if line.strip() == "---":
            index += 1
            break
        if line.strip():
            key, sep, value = line.partition(":")
            if not sep:
                raise ValueError(f"{path} has invalid front matter line: {line!r}")
            meta[key.strip()] = parse_scalar(value)
        index += 1

    body = "\n".join(lines[index:]).lstrip("\n")
    for key in ("title", "route"):
        if key not in meta:
            raise ValueError(f"{path} front matter is missing {key!r}")

    return {
        "title": meta["title"],
        "route": meta["route"],
        "content": body,
        "draft": bool(meta.get("draft", False)),
        "hidden": bool(meta.get("hidden", False)),
        "auth_required": bool(meta.get("auth_required", False)),
        "format": meta.get("format", "markdown"),
    }


def load_pages(pages_dir: str) -> list[dict[str, Any]]:
    page_root = Path(pages_dir)
    if not page_root.exists():
        raise FileNotFoundError(f"pages dir does not exist: {page_root}")
    return [parse_page(path) for path in sorted(page_root.glob("*.md"))]


def find_by_key(
    items: list[dict[str, Any]],
    *,
    key: str,
    value: str,
) -> dict[str, Any] | None:
    for item in items:
        if item.get(key) == value:
            return item
    return None


def upsert_page(
    client: CtfdClient,
    *,
    existing_pages: list[dict[str, Any]],
    page: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    existing = find_by_key(existing_pages, key="route", value=page["route"])
    if existing:
        print(f"update page: {page['route']}")
        if dry_run:
            updated = dict(existing)
            updated.update(page)
            return updated
        response = client.patch(f"/pages/{existing['id']}", page)
        return response["data"]

    print(f"create page: {page['route']}")
    if dry_run:
        created = {"id": None, **page}
        existing_pages.append(created)
        return created
    response = client.post("/pages", page)
    created = response["data"]
    existing_pages.append(created)
    return created


def build_challenge_payload(
    *,
    challenge: dict[str, Any],
    position: int,
    next_id: int | None,
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
        "requirements": challenge.get("requirements", {"prerequisites": []}),
    }
    if "connection_info" in challenge:
        payload["connection_info"] = challenge["connection_info"]
    if next_id is not None:
        payload["next_id"] = next_id
    return payload


def upsert_challenge(
    client: CtfdClient,
    *,
    existing_challenges: list[dict[str, Any]],
    payload: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    existing = find_by_key(existing_challenges, key="name", value=payload["name"])
    if existing:
        print(f"update challenge: {payload['name']}")
        if dry_run:
            updated = dict(existing)
            updated.update(payload)
            return updated
        response = client.patch(f"/challenges/{existing['id']}", payload)
        return response["data"]

    print(f"create challenge: {payload['name']}")
    if dry_run:
        created = {"id": None, **payload}
        existing_challenges.append(created)
        return created
    response = client.post("/challenges", payload)
    created = response["data"]
    existing_challenges.append(created)
    return created


def ensure_static_flag(
    client: CtfdClient,
    *,
    challenge_id: int | None,
    challenge_name: str,
    flag_value: str,
    dry_run: bool,
) -> None:
    print(f"sync flag: {challenge_name}")
    if dry_run or challenge_id is None:
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
    if dry_run or challenge_id is None:
        for index, _hint in enumerate(hints, start=1):
            print(f"sync hint: {challenge_name} :: Hint {index}")
        return

    existing_hints = client.get(f"/challenges/{challenge_id}/hints").get("data", [])
    expected_titles: set[str] = set()

    for index, hint in enumerate(hints, start=1):
        title = hint.get("title", f"Hint {index}")
        expected_titles.add(title)
        payload = {
            "challenge_id": challenge_id,
            "title": title,
            "content": hint["content"],
            "cost": hint.get("cost", 0),
            "requirements": hint.get("requirements", []),
        }
        existing = find_by_key(existing_hints, key="title", value=title)
        if existing:
            print(f"sync hint: {challenge_name} :: {title}")
            client.patch(f"/hints/{existing['id']}", payload)
        else:
            print(f"create hint: {challenge_name} :: {title}")
            response = client.post("/hints", payload)
            existing_hints.append(response["data"])

    for hint in existing_hints:
        if hint.get("title") not in expected_titles:
            print(f"delete stale hint: {challenge_name} :: {hint.get('title')}")
            client.delete(f"/hints/{hint['id']}")


def main() -> int:
    args = parse_args()
    if not args.token:
        raise SystemExit("missing --token and CTFD_TOKEN is not set")

    onboarding = load_json(args.onboarding_file)
    pages = load_pages(args.pages_dir)
    client = CtfdClient(args.base_url, args.token)

    existing_pages: list[dict[str, Any]] = []
    existing_challenges: list[dict[str, Any]] = []
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
        flag_entries = challenge.get("flags", [])
        if flag_entries:
            ensure_static_flag(
                client,
                challenge_id=synced.get("id"),
                challenge_name=payload["name"],
                flag_value=flag_entries[0]["content"],
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
