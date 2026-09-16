"""Collect + validate RAES operational evidence for a launched range (#1264).

The live-validation capstone launches an RAES package through the native path
and then reads back its operational evidence through the same redacted read seam
Mission Control uses (``shared.raes.projections``), asserting the backend really
provisioned: an operation receipt, a succeeded operation status, and a runtime
snapshot with topology plus verified content, account, and feature composition
("no vacuous pass"). It also re-asserts the redaction contract (ADR-031-R4) as
defense in depth, even though the read seam already redacts.

Read-only and import-clean: this consumes only ``shared.raes`` (no ``raes_*``,
no cyberscript), so it can run in the portal Django context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from shared.raes.projections import (
    RECORD_KIND_OPERATION_RECEIPT,
    RECORD_KIND_OPERATION_STATUS,
    RECORD_KIND_RUNTIME_SNAPSHOT,
    RaesOperationRecordProjection,
    list_operation_records,
)

_SUCCEEDED = "succeeded"
_COMPOSITION_TYPES = frozenset({"content-placement", "account-placement", "feature-binding"})

#: Backend realization detail that must never appear in host-exposed evidence
#: (ADR-031-R4). The read seam already redacts; this is a defense-in-depth check.
_FORBIDDEN_SUBSTRINGS = (
    "terraform",
    "ssm",
    "ami-",
    "cidr",
    "subnet",
    "secret",
    "password",
    "credential",
    "token",
    "-----begin",
)


class RaesEvidenceError(Exception):
    """Projected RAES evidence violated the redaction contract (ADR-031-R4)."""


@dataclass(frozen=True)
class RaesEvidenceSummary:
    """Bounded summary of the redacted RAES evidence for one launch."""

    request_id: str
    receipt_count: int
    status_count: int
    snapshot_count: int
    has_succeeded_status: bool
    snapshot_resource_count: int
    composition_resource_count: int
    verified_composition_types: frozenset[str]


def _assert_no_forbidden(projections: list[RaesOperationRecordProjection]) -> None:
    """Raise if any projected payload carries backend realization detail."""
    for projection in projections:
        blob = json.dumps(projection.payload, default=str).lower()
        for substring in _FORBIDDEN_SUBSTRINGS:
            if substring in blob:
                raise RaesEvidenceError(f"forbidden substring in projected RAES evidence: {substring}")


def _composition_type(resource: object, seen: set[str]) -> str | None:
    """Validate one projected resource and return its composition type, if any."""
    if not isinstance(resource, dict):
        raise RaesEvidenceError("runtime snapshot resource is invalid")
    resource_type = resource.get("resource_type")
    if resource_type not in _COMPOSITION_TYPES:
        return None
    if set(resource) != {"address", "resource_type", "status"}:
        raise RaesEvidenceError("composition evidence has forbidden detail")
    address = resource.get("address")
    if not isinstance(address, str) or not address or address in seen:
        raise RaesEvidenceError("composition evidence has an invalid or duplicate address")
    if resource.get("status") != "verified":
        raise RaesEvidenceError("composition evidence is not verified")
    seen.add(address)
    return resource_type


def _snapshot_composition_summary(snapshot: RaesOperationRecordProjection) -> tuple[int, frozenset[str]]:
    """Validate and summarize composition evidence in one runtime snapshot."""
    resources = snapshot.payload.get("resources") or []
    if not isinstance(resources, list):
        raise RaesEvidenceError("runtime snapshot resources are invalid")
    seen: set[str] = set()
    composition_types = {
        resource_type for resource in resources if (resource_type := _composition_type(resource, seen)) is not None
    }
    composition_count = len(seen)
    return composition_count, frozenset(composition_types)


def _composition_summary(
    snapshots: list[RaesOperationRecordProjection],
) -> tuple[int, frozenset[str]]:
    """Validate projected composition entries and return the strongest snapshot."""
    best_count = 0
    best_types: frozenset[str] = frozenset()
    for snapshot in snapshots:
        composition_count, composition_types = _snapshot_composition_summary(snapshot)
        if composition_count > best_count:
            best_count = composition_count
            best_types = composition_types
    return best_count, best_types


def collect_evidence(request_id: UUID | str, *, limit: int = 50) -> RaesEvidenceSummary:
    """Read the redacted receipt / status / snapshot evidence for ``request_id``.

    Raises RaesEvidenceError if any projected payload violates the redaction
    contract; otherwise returns a bounded summary for validation.
    """
    receipts = list_operation_records(request_id, RECORD_KIND_OPERATION_RECEIPT, limit=limit)
    statuses = list_operation_records(request_id, RECORD_KIND_OPERATION_STATUS, limit=limit)
    snapshots = list_operation_records(request_id, RECORD_KIND_RUNTIME_SNAPSHOT, limit=limit)
    _assert_no_forbidden([*receipts, *statuses, *snapshots])

    has_succeeded = any(projection.payload.get("status") == _SUCCEEDED for projection in statuses)
    resource_count = max(
        (len(projection.payload.get("resources") or []) for projection in snapshots),
        default=0,
    )
    composition_count, composition_types = _composition_summary(snapshots)
    return RaesEvidenceSummary(
        request_id=str(request_id),
        receipt_count=len(receipts),
        status_count=len(statuses),
        snapshot_count=len(snapshots),
        has_succeeded_status=has_succeeded,
        snapshot_resource_count=resource_count,
        composition_resource_count=composition_count,
        verified_composition_types=composition_types,
    )


def validate_evidence(summary: RaesEvidenceSummary) -> list[str]:
    """Return a list of validation problems ('no vacuous pass'); empty == valid."""
    problems: list[str] = []
    if summary.receipt_count < 1:
        problems.append("no operation_receipt evidence")
    if summary.status_count < 1:
        problems.append("no operation_status evidence")
    elif not summary.has_succeeded_status:
        problems.append("no succeeded operation_status")
    if summary.snapshot_count < 1:
        problems.append("no runtime_snapshot evidence")
    elif summary.snapshot_resource_count < 1:
        problems.append("runtime_snapshot recorded no realized resources (vacuous)")
    for resource_type in sorted(_COMPOSITION_TYPES - summary.verified_composition_types):
        problems.append(f"runtime_snapshot recorded no verified {resource_type} composition evidence")
    return problems
