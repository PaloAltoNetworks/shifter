"""Polaris-specific CTFd manifest helpers (issue #691).

These were tangled into ``sync_polaris_ctfd.py``. The split is by
specificity: ``ctfd_reconcile`` is generic CTFd row-reconciliation; this
module is Polaris-event constants and validation that only the Polaris
board cares about.

Owns:

- Authoritative challenge ordering for the Polaris board UI.
- Stale challenge names that the live board should delete on every sync.
- Source-manifest validation (``validate_manifest`` /
  ``validate_live_challenge_names``).
- Post-sync flag/hint verification (``verify_challenge_rows``).
- Prerequisite resolution (manifest id -> live CTFd id).
- ``SyncError`` — the dedicated exit-class the CLI catches.
"""

from __future__ import annotations

from typing import Any

from common import CtfdClient

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


def resolve_prerequisites(
    *,
    challenge: dict[str, Any],
    manifest_id_to_name: dict[int, str],
    name_to_live_id: dict[str, int | None],
) -> dict[str, Any]:
    """Translate manifest-id prerequisites into live CTFd ids."""
    raw_requirements = challenge.get("requirements", {})
    prerequisite_ids: list[int] = []
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


__all__ = [
    "ORDERED_CHALLENGE_NAMES",
    "STALE_CHALLENGE_NAMES",
    "SUPPORTED_FLAG_TYPES",
    "SyncError",
    "build_manifest_id_to_name",
    "resolve_prerequisites",
    "sort_challenges",
    "validate_live_challenge_names",
    "validate_manifest",
    "verify_challenge_rows",
]
