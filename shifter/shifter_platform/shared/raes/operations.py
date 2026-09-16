"""Persistence helpers for RAES operation sidecar records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from shared.models import RaesOperationRecord
from shared.raes.contracts import SHIFTER_BACKEND_PROFILE
from shared.schemas.raes_operation import canonical_raes_payload_digest


class RaesOperationRecordConflict(ValueError):
    """Raised when an idempotent replay carries conflicting operation content."""


@dataclass(frozen=True)
class RaesOperationRecordWrite:
    """Input contract for writing one RAES operation sidecar record."""

    request_id: UUID | str
    operation_id: str
    idempotency_key: str
    record_kind: str
    contract_version: str
    source_timestamp: datetime
    payload: dict[str, Any]
    payload_digest: str | None = None
    diagnostic_refs: dict[str, Any] | None = None
    range_id: UUID | str | None = None
    contract_kind: str = RaesOperationRecord.ContractKind.RAES
    contract_profile: str = SHIFTER_BACKEND_PROFILE
    owner: str = RaesOperationRecord.Owner.SHARED
    retention_expires_at: datetime | None = None


def _resolve_retention_expires_at(write: RaesOperationRecordWrite) -> datetime | None:
    """Return the row's retention boundary, deriving it from settings when unset.

    An explicit ``retention_expires_at`` is preserved. Otherwise the boundary is
    ``source_timestamp + RAES_OPERATION_RECORD_RETENTION_DAYS`` -- measured from
    the observation's logical time so idempotent replay is deterministic. A
    non-positive retention window disables the stamp (the row is never pruned).
    """
    if write.retention_expires_at is not None:
        return write.retention_expires_at
    days = settings.RAES_OPERATION_RECORD_RETENTION_DAYS
    if days <= 0:
        return None
    return write.source_timestamp + timedelta(days=days)


def _idempotency_lookup(write: RaesOperationRecordWrite) -> dict[str, Any]:
    """Build the database lookup tuple that defines replay identity."""
    return {
        "request_id": write.request_id,
        "record_kind": write.record_kind,
        "contract_version": write.contract_version,
        "contract_profile": write.contract_profile,
        "idempotency_key": write.idempotency_key,
    }


def _assert_replay_matches(
    existing: RaesOperationRecord,
    *,
    write: RaesOperationRecordWrite,
    payload_digest: str,
) -> None:
    """Reject idempotency-key reuse with different canonical content."""
    if (
        existing.operation_id != write.operation_id
        or existing.source_timestamp != write.source_timestamp
        or existing.payload_digest != payload_digest
    ):
        raise RaesOperationRecordConflict(
            "idempotency conflict: replay has different operation_id, source_timestamp, or payload_digest"
        )


def persist_raes_operation_record(write: RaesOperationRecordWrite) -> RaesOperationRecord:
    """Create or return an idempotent RAES operation sidecar record.

    The database enforces the replay key. The service enforces deterministic
    replay semantics by rejecting drift in the canonical content identity.
    """
    normalized_payload_digest = write.payload_digest or canonical_raes_payload_digest(write.payload)
    lookup = _idempotency_lookup(write)
    defaults = {
        "range_id": write.range_id,
        "operation_id": write.operation_id,
        "contract_kind": write.contract_kind,
        "source_timestamp": write.source_timestamp,
        "payload_digest": normalized_payload_digest,
        "payload": write.payload,
        "diagnostic_refs": write.diagnostic_refs or {},
        "owner": write.owner,
        "retention_expires_at": _resolve_retention_expires_at(write),
    }

    try:
        with transaction.atomic():
            record, created = RaesOperationRecord.objects.get_or_create(**lookup, defaults=defaults)
    except IntegrityError:
        record = RaesOperationRecord.objects.get(**lookup)
        created = False

    if not created:
        _assert_replay_matches(
            record,
            write=write,
            payload_digest=normalized_payload_digest,
        )
    return record


def prune_expired_raes_operation_records(*, batch_size: int) -> int:
    """Delete operation-record rows past their retention boundary; return the count.

    Runtime snapshots and adjacent operation records are bounded operational
    observations, not an archive. Rows whose ``retention_expires_at`` has passed
    are deleted oldest-boundary-first in a bounded batch; rows with no boundary
    (``retention_expires_at IS NULL``) are never touched. The delete is bounded
    by ``batch_size`` so a large backlog drains in fixed-size chunks rather than
    one unbounded query. Callers outside ``shared`` reach this seam through the
    ``run_raes_operation_record_prune`` management command instead of importing
    the model.
    """
    limit = max(1, int(batch_size))
    ids = list(
        RaesOperationRecord.objects.filter(retention_expires_at__lte=timezone.now())
        .order_by("retention_expires_at")
        .values_list("pk", flat=True)[:limit]
    )
    if not ids:
        return 0
    deleted, _details = RaesOperationRecord.objects.filter(pk__in=ids).delete()
    return deleted


#: Contract version for ``operation-status-v1`` sidecar records.
OPERATION_STATUS_CONTRACT_VERSION = "operation-status-v1"


def latest_operation_status_source_timestamp(request_id: UUID | str) -> datetime | None:
    """Return the source timestamp of the latest recorded operation status.

    This is the staleness anchor for status projection (#1274): callers outside
    the ``shared`` layer read it through this seam instead of importing the
    ``RaesOperationRecord`` model directly.
    """
    return (
        RaesOperationRecord.objects.filter(
            request_id=request_id,
            record_kind=RaesOperationRecord.RecordKind.OPERATION_STATUS,
        )
        .order_by("-source_timestamp", "-created_at")
        .values_list("source_timestamp", flat=True)
        .first()
    )


def persist_operation_status_record(
    *,
    request_id: UUID | str,
    operation_id: str,
    source_timestamp: datetime,
    payload: dict[str, Any],
    diagnostic_refs: dict[str, Any] | None = None,
    contract_version: str = OPERATION_STATUS_CONTRACT_VERSION,
    owner: str = RaesOperationRecord.Owner.ENGINE,
) -> RaesOperationRecord:
    """Persist one ``operation_status`` sidecar record idempotently.

    Encapsulates the ``record_kind`` and idempotency-key convention for
    operation-status observations so callers outside ``shared`` do not touch the
    ``RaesOperationRecord`` model. The idempotency key is deterministic in the
    operation id and observation timestamp, so re-delivery of the same
    observation is a no-op (or a conflict when the content drifts).
    """
    write = RaesOperationRecordWrite(
        request_id=request_id,
        operation_id=operation_id,
        idempotency_key=f"operation_status:{operation_id}:{source_timestamp.isoformat()}",
        record_kind=RaesOperationRecord.RecordKind.OPERATION_STATUS,
        contract_version=contract_version,
        source_timestamp=source_timestamp,
        payload=payload,
        diagnostic_refs=diagnostic_refs or {},
        owner=owner,
    )
    return persist_raes_operation_record(write)


RUNTIME_SNAPSHOT_CONTRACT_VERSION = "runtime-snapshot-v1"


def persist_runtime_snapshot_record(
    *,
    request_id: UUID | str,
    operation_id: str,
    source_timestamp: datetime,
    payload: dict[str, Any],
    range_id: UUID | str | None = None,
    contract_version: str = RUNTIME_SNAPSHOT_CONTRACT_VERSION,
    owner: str = RaesOperationRecord.Owner.ENGINE,
) -> RaesOperationRecord:
    """Persist one ``runtime_snapshot`` sidecar record idempotently.

    Encapsulates the ``record_kind`` and idempotency-key convention for a
    provisioned-state snapshot so callers outside ``shared`` do not touch the
    ``RaesOperationRecord`` model. The idempotency key is deterministic in the
    operation id and observation timestamp, so re-delivery of the same snapshot is
    a no-op (or a conflict when the content drifts). The ``payload`` must carry the
    required ``operation_id`` + ``resources`` keys and is bounded/redacted by the
    write-boundary validator (ADR-031-R4) like every RAES operation record.
    """
    write = RaesOperationRecordWrite(
        request_id=request_id,
        operation_id=operation_id,
        idempotency_key=f"runtime_snapshot:{operation_id}:{source_timestamp.isoformat()}",
        record_kind=RaesOperationRecord.RecordKind.RUNTIME_SNAPSHOT,
        contract_version=contract_version,
        source_timestamp=source_timestamp,
        payload=payload,
        range_id=range_id,
        owner=owner,
    )
    return persist_raes_operation_record(write)


OPERATION_RECEIPT_CONTRACT_VERSION = "operation-receipt-v1"


def persist_operation_receipt_record(
    *,
    request_id: UUID | str,
    operation_id: str,
    source_timestamp: datetime,
    payload: dict[str, Any],
    range_id: UUID | str | None = None,
    contract_version: str = OPERATION_RECEIPT_CONTRACT_VERSION,
    owner: str = RaesOperationRecord.Owner.ENGINE,
) -> RaesOperationRecord:
    """Persist one ``operation_receipt`` sidecar record idempotently.

    Encapsulates the ``record_kind`` and idempotency-key convention for the
    accept-time receipt so callers outside ``shared`` (the engine RAES dispatch
    path) do not import the ``RaesOperationRecord`` model. The idempotency key is
    deterministic in the operation id, so re-accepting the same request is a
    no-op (or a conflict when the content drifts).
    """
    write = RaesOperationRecordWrite(
        request_id=request_id,
        operation_id=operation_id,
        idempotency_key=f"operation_receipt:{operation_id}",
        record_kind=RaesOperationRecord.RecordKind.OPERATION_RECEIPT,
        contract_version=contract_version,
        source_timestamp=source_timestamp,
        payload=payload,
        range_id=range_id,
        owner=owner,
    )
    return persist_raes_operation_record(write)
