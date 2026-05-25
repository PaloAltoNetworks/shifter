"""Generic CTFd reconciliation helpers (issue #691).

These helpers were duplicated across ``sync_polaris_ctfd_onboarding.py``
(authoritative version), ``sync_polaris_ctfd.py`` (re-imported wrappers
plus its own page sync), and ``seed_ctfd.py`` (parallel re-implementation
with slightly different flag/hint semantics).

The module owns the **generic** CTFd row-reconciliation surface:

- ``find_by_key`` / ``reconcile_rows`` — add/match/delete keyed on a
  caller-supplied ``row_key``.
- ``upsert_page`` / ``upsert_challenge`` / ``build_challenge_payload`` —
  CTFd object upsert keyed by ``route`` and ``name`` respectively.
- ``normalize_flag`` / ``normalize_hints`` — manifest-shape to CTFd-row
  shape.
- ``ensure_flags`` / ``ensure_hints`` — full reconcile on
  ``(type, content)`` and ``title`` respectively, with deletion of stale
  rows. The hint write payload carries the polymorphic ``type: standard``
  discriminator (skipping it shipped NULL hint types and participant-side
  500s on a previous regression).
- ``parse_scalar`` / ``parse_page`` / ``load_pages`` / ``load_json`` —
  source-manifest readers used by every page+challenge sync flow.

Anything Polaris-specific (challenge ordering, prereq resolution, manifest
validation rules) lives in ``polaris_manifest.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from common import CtfdClient


# Source flags use the canonical ``FLAG{<16-hex>}`` wrapper. The bare-hex
# alias (issue #705) is derived only when the wrapper is well-formed and the
# hex body is exactly 16 chars — the production contract documented in
# ``docs/architecture/polaris-bare-hash-flag-preflight-705.md``. Anything
# else stays as the operator wrote it. ``polaris_manifest.validate_manifest``
# rejects malformed or non-16-hex wrappers upstream so the helper here only
# ever sees the clean canonical shape on the canonical path.
_CANONICAL_FLAG_WRAPPER_RE = re.compile(r"^FLAG\{([0-9a-fA-F]{16})\}$")


# -----------------------------------------------------------------------------
# Source-manifest readers
# -----------------------------------------------------------------------------


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
    """Parse a CTFd page Markdown file with front-matter into a page body."""
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


# -----------------------------------------------------------------------------
# Row-set reconciliation
# -----------------------------------------------------------------------------


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


# -----------------------------------------------------------------------------
# CTFd-row builders + upserts
# -----------------------------------------------------------------------------


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
    next_id: int | None = None,
    requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the CTFd ``/challenges`` payload body from a source-manifest entry.

    Source manifests for both the Polaris board and the agentic workshop
    flow through this builder. Callers always own the ``requirements`` policy
    they want CTFd to persist:

    - Polaris first pass writes ``{"prerequisites": []}`` so unresolved
      source-manifest ids never reach the live CTFd authorization gate.
    - Polaris second pass passes ``resolve_prerequisites(...)`` so live
      CTFd ids are written once every challenge id exists.
    - Workshop seeding passes explicit ``prerequisites`` (empty for the
      first pass, [user_challenge_id] for the second).

    When a caller omits ``requirements`` the builder defaults to empty
    prerequisites, NOT a copy of ``challenge["requirements"]``. Copying raw
    source-manifest requirements through this shared helper would persist
    pre-resolution manifest ids as live CTFd prerequisite ids, which can
    bypass intended challenge gates if a sync is interrupted before the
    resolved pass runs.
    """
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
        "requirements": (
            requirements if requirements is not None else {"prerequisites": []}
        ),
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


# -----------------------------------------------------------------------------
# Flag / hint shape normalizers + reconcilers
# -----------------------------------------------------------------------------


def normalize_flag(flag: dict[str, Any]) -> dict[str, Any]:
    """Return a CTFd flag-row body from a source-JSON flag entry.

    Canonical ``FLAG{<16-hex>}`` static source content is aliased to a
    single case-insensitive regex row that accepts either the wrapped form
    or the bare ``<16-hex>`` (issue #705). The canonical answer in repo
    content stays ``FLAG{<16-hex>}``; only the live CTFd row shape changes,
    so existing walkthroughs and challenge descriptions are untouched.

    Source flags already typed ``regex``, and ``static`` entries whose
    content is not a canonical FLAG wrapper, pass through unchanged.
    """
    source_type = flag.get("type", "static")
    content = flag["content"]
    if source_type == "static":
        match = _CANONICAL_FLAG_WRAPPER_RE.match(content)
        if match:
            hex_part = match.group(1)
            return {
                "type": "regex",
                "content": rf"^(?:FLAG\{{{hex_part}\}}|{hex_part})$",
                "data": "case_insensitive",
            }
    return {
        "type": source_type,
        "content": content,
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


def get_all_items(
    client: CtfdClient,
    path: str,
    query: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Paginate through a CTFd list endpoint and return all rows."""
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


__all__ = [
    "build_challenge_payload",
    "ensure_flags",
    "ensure_hints",
    "find_by_key",
    "get_all_items",
    "load_json",
    "load_pages",
    "normalize_flag",
    "normalize_hints",
    "parse_page",
    "parse_scalar",
    "reconcile_rows",
    "upsert_challenge",
    "upsert_page",
]
