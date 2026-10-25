"""Fail closed unless a foundation plan only migrates the image network."""

from __future__ import annotations

import json
import sys

_RESOURCES = (
    "google_compute_network.image_build[0]",
    "google_compute_subnetwork.image_build[0]",
    "google_compute_router.image_build[0]",
    "google_compute_router_nat.image_build[0]",
    "google_compute_firewall.image_build_iap[0]",
    "google_compute_firewall.image_validate_iap[0]",
)
_MODULE_PREFIX = "module.image_build_network."
_IAP_FIREWALL = _MODULE_PREFIX + "google_compute_firewall.image_build_iap[0]"


def _allowed_firewall_update(change: dict) -> bool:
    before = change.get("before")
    after = change.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    if {key: value for key, value in before.items() if key != "allow"} != {
        key: value for key, value in after.items() if key != "allow"
    }:
        return False
    return before.get("allow") == [{"protocol": "tcp", "ports": ["22", "5986"]}] and after.get("allow") == [
        {"protocol": "tcp", "ports": ["22", "2222", "5986"]}
    ]


def validate_plan(plan: dict) -> tuple[int, int]:
    """Return (address moves, firewall updates), or reject the whole plan."""
    if not isinstance(plan, dict) or not isinstance(plan.get("resource_changes"), list):
        raise ValueError("Terraform plan has no resource changes")

    expected_moves = {name: _MODULE_PREFIX + name for name in _RESOURCES}
    found_moves: set[str] = set()
    firewall_updates = 0
    for resource in plan["resource_changes"]:
        address = resource.get("address")
        previous = resource.get("previous_address")
        change = resource.get("change") or {}
        actions = change.get("actions")

        if previous is not None:
            if expected_moves.get(previous) != address or previous in found_moves:
                raise ValueError(f"Unexpected Terraform address move: {previous} -> {address}")
            found_moves.add(previous)

        if actions == ["no-op"]:
            continue
        if address == _IAP_FIREWALL and actions == ["update"] and _allowed_firewall_update(change):
            firewall_updates += 1
            continue
        raise ValueError(f"Unexpected Terraform resource action at {address}: {actions}")

    if found_moves and found_moves != set(expected_moves):
        raise ValueError("Terraform plan moves only part of the image network")
    if firewall_updates > 1:
        raise ValueError("Terraform plan updates the image-build firewall more than once")
    for output_name, output in (plan.get("output_changes") or {}).items():
        if output.get("actions") != ["no-op"]:
            raise ValueError(f"Unexpected Terraform output change: {output_name}")
    for drift in plan.get("resource_drift") or []:
        drift_change = drift.get("change") or {}
        if drift_change.get("actions") == ["no-op"]:
            continue
        before = drift_change.get("before")
        after = drift_change.get("after")
        # Project IAM policy etags change when any binding changes. The
        # foundation still proposes no IAM action; tolerate only this
        # provider-observed metadata refresh, never a binding change.
        if (
            drift_change.get("actions") == ["update"]
            and isinstance(before, dict)
            and isinstance(after, dict)
            and {key: value for key, value in before.items() if key != "etag"}
            == {key: value for key, value in after.items() if key != "etag"}
        ):
            continue
        raise ValueError(f"Live Terraform resource drift detected: {drift.get('address')}")
    return len(found_moves), firewall_updates


def main() -> int:
    try:
        moves, updates = validate_plan(json.load(sys.stdin))
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Foundation image-network plan rejected: {exc}", file=sys.stderr)
        return 1
    print(f"Foundation image-network plan accepted: {moves} address moves, {updates} firewall updates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
