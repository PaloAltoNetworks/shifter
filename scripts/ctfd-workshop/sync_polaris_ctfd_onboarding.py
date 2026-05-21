#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

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


def reconcile_rows(
    *,
    source_rows: list[dict[str, Any]],
    live_rows: list[dict[str, Any]],
    row_key: Callable[[dict[str, Any]], Any],
    on_create: Callable[[dict[str, Any]], None],
    on_match: Callable[[dict[str, Any], dict[str, Any]], None],
    on_delete: Callable[[dict[str, Any]], None],
) -> None:
    """Reconcile a set of CTFd child rows against the source manifest.

    Add-missing / patch-on-match / delete-stale, keyed by ``row_key``. This is
    the shared seam so flags and hints follow the same expected-vs-live
    discipline instead of one-off per-row helpers.
    """
    live_by_key: dict[Any, dict[str, Any]] = {}
    for row in live_rows:
        live_by_key.setdefault(row_key(row), row)

    expected_keys: set[Any] = set()
    for source in source_rows:
        key = row_key(source)
        expected_keys.add(key)
        match = live_by_key.get(key)
        if match is None:
            on_create(source)
        else:
            on_match(match, source)

    for key, row in live_by_key.items():
        if key not in expected_keys:
            on_delete(row)


def normalize_flag(flag: dict[str, Any]) -> dict[str, Any]:
    """Return a CTFd flag-row body from a source-JSON flag entry."""
    return {
        "type": flag.get("type", "static"),
        "content": flag["content"],
        "data": flag.get("data", ""),
    }


def normalize_hints(hints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return CTFd hint-row bodies, deriving default titles by position."""
    normalized: list[dict[str, Any]] = []
    for index, hint in enumerate(hints, start=1):
        normalized.append(
            {
                "title": hint.get("title", f"Hint {index}"),
                "content": hint["content"],
                "cost": hint.get("cost", 0),
                "requirements": hint.get("requirements", []),
            }
        )
    return normalized


def ensure_flags(
    client: CtfdClient,
    *,
    challenge_id: int | None,
    challenge_name: str,
    flags: list[dict[str, Any]],
    dry_run: bool,
) -> None:
    """Reconcile every source flag against the challenge's live CTFd flag rows.

    Idempotent across re-syncs: flags are keyed by ``(type, content)``, missing
    rows are created, stale rows removed. Flag content is never logged.
    """
    expected = [normalize_flag(flag) for flag in flags]
    if dry_run or challenge_id is None:
        for flag in expected:
            print(f"sync flag: {challenge_name} :: {flag['type']}")
        return

    live_flags = client.get("/flags", {"challenge_id": challenge_id}).get("data", [])

    def on_create(flag: dict[str, Any]) -> None:
        print(f"create flag: {challenge_name} :: {flag['type']}")
        client.post("/flags", {"challenge_id": challenge_id, **flag})

    def on_match(live_flag: dict[str, Any], flag: dict[str, Any]) -> None:
        if live_flag.get("data", "") != flag["data"]:
            print(f"update flag: {challenge_name} :: {flag['type']}")
            client.patch(f"/flags/{live_flag['id']}", {"challenge_id": challenge_id, **flag})
        else:
            print(f"keep flag: {challenge_name} :: {flag['type']}")

    def on_delete(live_flag: dict[str, Any]) -> None:
        print(f"delete stale flag: {challenge_name} :: {live_flag.get('type')}")
        client.delete(f"/flags/{live_flag['id']}")

    reconcile_rows(
        source_rows=expected,
        live_rows=live_flags,
        row_key=lambda flag: (flag.get("type", "static"), flag.get("content")),
        on_create=on_create,
        on_match=on_match,
        on_delete=on_delete,
    )


def ensure_hints(
    client: CtfdClient,
    *,
    challenge_id: int | None,
    challenge_name: str,
    hints: list[dict[str, Any]],
    dry_run: bool,
) -> None:
    """Reconcile source hints against the challenge's live CTFd hint rows.

    Hint write payloads carry the polymorphic ``type: standard`` discriminator;
    omitting it produced NULL hint types and participant-facing 500s.
    """
    expected = normalize_hints(hints)
    if dry_run or challenge_id is None:
        for hint in expected:
            print(f"sync hint: {challenge_name} :: {hint['title']}")
        return

    live_hints = client.get(f"/challenges/{challenge_id}/hints").get("data", [])

    def body(hint: dict[str, Any]) -> dict[str, Any]:
        return {
            "challenge_id": challenge_id,
            "type": "standard",
            "title": hint["title"],
            "content": hint["content"],
            "cost": hint["cost"],
            "requirements": hint["requirements"],
        }

    def on_create(hint: dict[str, Any]) -> None:
        print(f"create hint: {challenge_name} :: {hint['title']}")
        client.post("/hints", body(hint))

    def on_match(live_hint: dict[str, Any], hint: dict[str, Any]) -> None:
        print(f"sync hint: {challenge_name} :: {hint['title']}")
        client.patch(f"/hints/{live_hint['id']}", body(hint))

    def on_delete(live_hint: dict[str, Any]) -> None:
        print(f"delete stale hint: {challenge_name} :: {live_hint.get('title')}")
        client.delete(f"/hints/{live_hint['id']}")

    reconcile_rows(
        source_rows=expected,
        live_rows=live_hints,
        row_key=lambda hint: hint["title"],
        on_create=on_create,
        on_match=on_match,
        on_delete=on_delete,
    )


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
