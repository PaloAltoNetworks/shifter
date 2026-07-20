"""Collect + validate ACES operational evidence for a launched range (#1264).

The live-validation capstone launches an ACES package through the native path
and then reads back its operational evidence through the same redacted read seam
Mission Control uses (``shared.aces.projections``), asserting the backend really
provisioned: an operation receipt, a succeeded operation status, and a runtime
snapshot with at least one realized resource ("no vacuous pass"). It also
re-asserts the redaction contract (ADR-031-R4) as defense in depth, even though
the read seam already redacts.

Read-only and import-clean: this consumes only ``shared.aces`` (no ``aces_*``,
no cyberscript), so it can run in the portal Django context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from shared.aces.projections import (
    RECORD_KIND_OPERATION_RECEIPT,
    RECORD_KIND_OPERATION_STATUS,
    RECORD_KIND_RUNTIME_SNAPSHOT,
    AcesOperationRecordProjection,
    list_operation_records,
)

_SUCCEEDED = "succeeded"

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


class AcesEvidenceError(Exception):
    """Projected ACES evidence violated the redaction contract (ADR-031-R4)."""


@dataclass(frozen=True)
class AcesEvidenceSummary:
    """Bounded summary of the redacted ACES evidence for one launch."""

    request_id: str
    receipt_count: int
    status_count: int
    snapshot_count: int
    has_succeeded_status: bool
    snapshot_resource_count: int


def _assert_no_forbidden(projections: list[AcesOperationRecordProjection]) -> None:
    """Raise if any projected payload carries backend realization detail."""
    for projection in projections:
        blob = json.dumps(projection.payload, default=str).lower()
        for substring in _FORBIDDEN_SUBSTRINGS:
            if substring in blob:
                raise AcesEvidenceError(f"forbidden substring in projected ACES evidence: {substring}")


def collect_evidence(request_id: UUID | str, *, limit: int = 50) -> AcesEvidenceSummary:
    """Read the redacted receipt / status / snapshot evidence for ``request_id``.

    Raises AcesEvidenceError if any projected payload violates the redaction
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
    return AcesEvidenceSummary(
        request_id=str(request_id),
        receipt_count=len(receipts),
        status_count=len(statuses),
        snapshot_count=len(snapshots),
        has_succeeded_status=has_succeeded,
        snapshot_resource_count=resource_count,
    )


def validate_evidence(summary: AcesEvidenceSummary) -> list[str]:
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
    return problems
