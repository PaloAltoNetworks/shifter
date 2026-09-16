"""Bounded completion transport shared with the RAES-free provisioner."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_KEYS = {
    "schema_version",
    "plan_digest",
    "operation_id",
    "generation_id",
    "resources",
    "operating_systems",
    "compute_substrates",
}
MAX_COMPLETION_RESOURCES = 128
MAX_COMPLETION_INSTANCES = 64
_MAX_BYTES = 262144


def plan_digest(plan: Mapping[str, Any]) -> str:
    """Bind observations to the exact immutable serialized input."""
    body = json.dumps(dict(plan), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(body).hexdigest()


def validate_completion_evidence(value: object) -> dict[str, Any]:
    """Validate the closed evidence shape without trusting its claimed outcome."""
    if not isinstance(value, dict) or set(value) != _KEYS:
        raise ValueError("invalid RAES completion evidence fields")
    if value["schema_version"] != "shifter-raes-completion-v1":
        raise ValueError("unsupported RAES completion evidence version")
    for field in ("plan_digest", "operation_id", "generation_id"):
        if not isinstance(value[field], str) or not value[field] or len(value[field]) > 128:
            raise ValueError("invalid RAES completion identity")
    shapes = {
        "resources": {"address", "resource_type", "status"},
        "operating_systems": {"instance_key", "family", "distribution", "version"},
        "compute_substrates": {"instance_key", "value"},
    }
    value_limits = {
        "resources": {"address": 256, "resource_type": 64, "status": 64},
        "operating_systems": {"instance_key": 260, "family": 128, "distribution": 128, "version": 128},
        "compute_substrates": {"instance_key": 260, "value": 128},
    }
    limits = {
        "resources": MAX_COMPLETION_RESOURCES,
        "operating_systems": MAX_COMPLETION_INSTANCES,
        "compute_substrates": MAX_COMPLETION_INSTANCES,
    }
    for field, keys in shapes.items():
        _validate_evidence_rows(value[field], keys, limits[field], value_limits[field])
    if len(json.dumps(value, allow_nan=False).encode()) > _MAX_BYTES:
        raise ValueError("RAES completion evidence exceeds its size bound")
    return value


def _validate_evidence_rows(rows: object, keys: set[str], limit: int, value_limits: Mapping[str, int]) -> None:
    """Handle validate evidence rows."""
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError("invalid RAES completion evidence collection")
    identities = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != keys:
            raise ValueError("invalid RAES completion evidence row")
        if any(not isinstance(item, str) or not item or len(item) > value_limits[key] for key, item in row.items()):
            raise ValueError("invalid RAES completion evidence value")
        identity = row.get("instance_key", row.get("address"))
        if identity in identities:
            raise ValueError("duplicate RAES completion evidence identity")
        identities.add(identity)


def build_completion_evidence(
    plan: Mapping[str, Any],
    *,
    resources: list[dict[str, str]],
    operating_systems: object,
    compute_substrates: object,
    generation_id: str | None = None,
) -> dict[str, Any]:
    """Transport verified worker outputs; admission rechecks the input binding."""
    return validate_completion_evidence(
        {
            "schema_version": "shifter-raes-completion-v1",
            "plan_digest": plan_digest(plan),
            "operation_id": plan.get("operation_id"),
            "generation_id": generation_id or plan.get("operation_id"),
            "resources": resources,
            "operating_systems": operating_systems,
            "compute_substrates": compute_substrates,
        }
    )
