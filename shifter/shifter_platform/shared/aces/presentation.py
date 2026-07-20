"""Compact presentation projection of ACES operation state for range UI surfaces (#1276).

Mission Control range cards want a *secondary, read-only* view of ACES operation
state alongside the authoritative Shifter range lifecycle. This module is the
single presentation seam over the #1275 read API (:mod:`shared.aces.projections`):
it reads the latest redacted operation-status / runtime-snapshot / operation-receipt
records for a ``request_id`` and reduces them to a bounded, UI-safe summary.

It is deliberately narrow:

- it reads through ``shared.aces.projections.list_operation_records`` (already
  response-allowlisted) and never touches ``AcesOperationRecord`` or raw payloads;
- runtime snapshots are reduced to a resource *count* plus a stable reference --
  the raw ``resources`` structure never leaves this layer
  (preflight ``docs/architecture/aces-mission-control-range-projections-preflight-1276.md``);
- ACES operation status is mapped to a display label kept explicitly distinct
  from :class:`shared.enums.ResourceStatus`, so the UI never conflates the ACES
  operation lifecycle with the Shifter range lifecycle;
- it returns ``None`` for legacy / non-ACES ranges (no sidecar rows), so those
  ranges render exactly as before.

The seam is parameterized by ``request_id`` and ``contract_profile``; a future
backend profile, contract version, or richer detail surface adds a branch here
rather than editing range DTOs, websocket payloads, templates, or JavaScript.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from shared.aces.contracts import SHIFTER_BACKEND_PROFILE
from shared.aces.participant_runtime_projections import (
    RECORD_KIND_PARTICIPANT_IMPLEMENTATION,
    RECORD_KIND_PARTICIPANT_RUNTIME,
    AcesParticipantRuntimeRecordProjection,
    list_participant_runtime_records,
)
from shared.aces.projections import (
    MAX_HISTORY_LIMIT,
    RECORD_KIND_OPERATION_RECEIPT,
    RECORD_KIND_OPERATION_STATUS,
    RECORD_KIND_RUNTIME_SNAPSHOT,
    AcesOperationRecordProjection,
    list_operation_records,
)
from shared.aces.status import (
    ACES_STATE_ACCEPTED,
    ACES_STATE_CANCELLED,
    ACES_STATE_FAILED,
    ACES_STATE_RUNNING,
    ACES_STATE_SUCCEEDED,
)
from shared.schemas.range import InstanceContext

#: Access-channel discriminators for the #1290 participant/runtime projection.
#: Each is a read-only availability + target-reference pair; see
#: ``build_range_participant_runtime_projection`` for the derivation rules and
#: the preflight note for why these never carry signed URLs, tokens, or
#: commands.
ACCESS_CHANNEL_BROWSER_TERMINAL: str = "browser_terminal"
ACCESS_CHANNEL_GUACAMOLE_RDP: str = "guacamole_rdp"
ACCESS_CHANNEL_GUACAMOLE_RANGE_SSH: str = "guacamole_range_ssh"
ACCESS_CHANNEL_GUACAMOLE_NGFW_SSH: str = "guacamole_ngfw_ssh"
ACCESS_CHANNEL_BACKEND_COMMAND: str = "backend_command"

#: Read-only per-instance access-channel capability map, keyed on the canonical
#: instance ``os_type`` (the same attribute the range UI already displays).
#: Deriving from ``os_type`` rather than ``role`` keeps the projection from
#: advertising channels that are not actually openable for a target -- e.g. RDP
#: on a Linux box, or a browser SSH terminal on a Windows box. The next protocol
#: variation is one entry here, not a new branch across range views/templates.
ACCESS_CHANNELS_BY_OS_TYPE: dict[str, tuple[str, ...]] = {
    "windows": (ACCESS_CHANNEL_GUACAMOLE_RDP,),
    "kali": (ACCESS_CHANNEL_BROWSER_TERMINAL, ACCESS_CHANNEL_GUACAMOLE_RANGE_SSH),
    "ubuntu": (ACCESS_CHANNEL_BROWSER_TERMINAL, ACCESS_CHANNEL_GUACAMOLE_RANGE_SSH),
    "panos": (ACCESS_CHANNEL_GUACAMOLE_NGFW_SSH,),
}

#: Display labels for the ACES operation lifecycle. Phrased with an "Operation"
#: prefix so they never collide with Shifter ``ResourceStatus`` display values;
#: a drift test asserts distinctness.
ACES_OPERATION_STATUS_LABELS: dict[str, str] = {
    ACES_STATE_ACCEPTED: "Operation accepted",
    ACES_STATE_RUNNING: "Operation running",
    ACES_STATE_SUCCEEDED: "Operation succeeded",
    ACES_STATE_FAILED: "Operation failed",
    ACES_STATE_CANCELLED: "Operation cancelled",
}

#: Fallback label when no status record exists or the state is unrecognized.
UNKNOWN_STATUS_LABEL = "Operation status unavailable"


def status_label_for(status: str | None) -> str:
    """Return the UI display label for an ACES operation status."""
    if status is None:
        return UNKNOWN_STATUS_LABEL
    return ACES_OPERATION_STATUS_LABELS.get(status, UNKNOWN_STATUS_LABEL)


def _iso(value: datetime | None) -> str | None:
    """Serialize a datetime to ISO-8601 for JSON responses, or ``None``."""
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class RangeAcesSnapshotSummary:
    """Bounded summary of the latest runtime snapshot (never the raw resources)."""

    observed_at: datetime | None
    resource_count: int
    snapshot_ref: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "observed_at": _iso(self.observed_at),
            "resource_count": self.resource_count,
            "snapshot_ref": self.snapshot_ref,
        }


@dataclass(frozen=True)
class RangeAcesReceiptSummary:
    """Bounded summary of the latest operation receipt (reference only)."""

    status: str | None
    observed_at: datetime | None
    receipt_ref: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "observed_at": _iso(self.observed_at),
            "receipt_ref": self.receipt_ref,
        }


@dataclass(frozen=True)
class RangeAcesProjection:
    """Compact, UI-safe summary of a range's latest ACES operation state.

    ``status`` is the raw ACES operation state; ``status_label`` is the
    display label kept distinct from Shifter ``ResourceStatus``. Snapshot and
    receipt are optional bounded summaries.
    """

    operation_id: str | None
    status: str | None
    status_label: str
    status_reason: str | None
    observed_at: datetime | None
    contract_profile: str
    contract_version: str | None
    snapshot: RangeAcesSnapshotSummary | None
    receipt: RangeAcesReceiptSummary | None

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-safe dict for range read responses (shared by both paths)."""
        return {
            "operation_id": self.operation_id,
            "status": self.status,
            "status_label": self.status_label,
            "status_reason": self.status_reason,
            "observed_at": _iso(self.observed_at),
            "contract_profile": self.contract_profile,
            "contract_version": self.contract_version,
            "snapshot": self.snapshot.to_payload() if self.snapshot else None,
            "receipt": self.receipt.to_payload() if self.receipt else None,
        }


def _latest(request_id: UUID | str, record_kind: str, contract_profile: str) -> AcesOperationRecordProjection | None:
    """Return the newest redacted projection for one record kind, or ``None``."""
    rows = list_operation_records(request_id, record_kind, limit=1, contract_profile=contract_profile)
    return rows[0] if rows else None


def _snapshot_summary(record: AcesOperationRecordProjection) -> RangeAcesSnapshotSummary:
    """Reduce a snapshot projection to a resource count + stable reference."""
    resources = record.payload.get("resources")
    resource_count = len(resources) if isinstance(resources, (list, tuple, dict)) else 0
    ref = record.payload.get("snapshot_ref")
    return RangeAcesSnapshotSummary(
        observed_at=record.source_timestamp,
        resource_count=resource_count,
        snapshot_ref=ref if isinstance(ref, str) else None,
    )


def _receipt_summary(record: AcesOperationRecordProjection) -> RangeAcesReceiptSummary:
    """Reduce a receipt projection to status + stable reference."""
    ref = record.payload.get("receipt_ref")
    status = record.payload.get("status")
    return RangeAcesReceiptSummary(
        status=status if isinstance(status, str) else None,
        observed_at=record.source_timestamp,
        receipt_ref=ref if isinstance(ref, str) else None,
    )


def build_range_aces_projection(
    request_id: UUID | str,
    *,
    contract_profile: str = SHIFTER_BACKEND_PROFILE,
) -> RangeAcesProjection | None:
    """Build the compact ACES projection for a range's ``request_id``.

    Reads the latest operation-status, runtime-snapshot, and operation-receipt
    records through the #1275 read seam and reduces them to a bounded summary.
    Returns ``None`` when the range has no ACES sidecar rows (legacy / non-ACES
    ranges), so callers can treat the projection as absent.
    """
    status_record = _latest(request_id, RECORD_KIND_OPERATION_STATUS, contract_profile)
    snapshot_record = _latest(request_id, RECORD_KIND_RUNTIME_SNAPSHOT, contract_profile)
    receipt_record = _latest(request_id, RECORD_KIND_OPERATION_RECEIPT, contract_profile)

    primary = status_record or snapshot_record or receipt_record
    if primary is None:
        return None

    if status_record is not None:
        raw_status = status_record.payload.get("status")
        status = raw_status if isinstance(raw_status, str) else None
        reason = status_record.payload.get("status_reason")
        status_reason = reason if isinstance(reason, str) else None
        observed_at = status_record.source_timestamp
    else:
        status = None
        status_reason = None
        observed_at = None

    operation_id = primary.payload.get("operation_id")

    return RangeAcesProjection(
        operation_id=operation_id if isinstance(operation_id, str) else None,
        status=status,
        status_label=status_label_for(status),
        status_reason=status_reason,
        observed_at=observed_at,
        contract_profile=primary.contract_profile,
        contract_version=primary.contract_version,
        snapshot=_snapshot_summary(snapshot_record) if snapshot_record else None,
        receipt=_receipt_summary(receipt_record) if receipt_record else None,
    )


@dataclass(frozen=True)
class RangeParticipantSummary:
    """Bounded per-participant summary: latest implementation + runtime state (#1290).

    ``implementation`` and ``runtime`` are already-reduced, JSON-safe dicts (or
    ``None`` when no record of that kind exists for the participant); they are
    built by the module-level reducer functions below from the
    response-allowlisted payload the #1288 read seam already returns, so this
    dataclass only holds the finished shape.
    """

    participant_ref: str
    implementation: dict[str, Any] | None
    runtime: dict[str, Any] | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "participant_ref": self.participant_ref,
            "implementation": self.implementation,
            "runtime": self.runtime,
        }


@dataclass(frozen=True)
class RangeAccessChannel:
    """One read-only access-channel availability + target reference (#1290).

    ``channel`` is one of the ``ACCESS_CHANNEL_*`` discriminators; ``target_ref``
    is a stable instance uuid or ``request_id`` string. Never a signed URL,
    token, credential, or command.
    """

    channel: str
    target_ref: str

    def to_payload(self) -> dict[str, Any]:
        return {"channel": self.channel, "target_ref": self.target_ref}


@dataclass(frozen=True)
class RangeParticipantRuntimeProjection:
    """Compact, UI-safe summary of a range's ACES participant/runtime state (#1290).

    Sibling to :class:`RangeAcesProjection`: ``participants`` is a bounded,
    latest-per-``participant_ref`` list; ``access_channels`` is a pure
    derivation over the range's instances (plus one range-level backend
    command channel). ``None`` at the caller when there are zero participant
    rows, so non-ACES ranges are unaffected.
    """

    participants: list[RangeParticipantSummary]
    access_channels: list[RangeAccessChannel]

    def to_payload(self) -> dict[str, Any]:
        return {
            "participants": [p.to_payload() for p in self.participants],
            "access_channels": [c.to_payload() for c in self.access_channels],
        }


def _implementation_summary(record: AcesParticipantRuntimeRecordProjection) -> dict[str, Any]:
    """Reduce a participant-implementation projection to the response-safe shape."""
    payload = record.payload
    status = payload.get("status")
    backend_name = payload.get("backend_name")
    implementation_ref = payload.get("implementation_ref")
    return {
        "status": status if isinstance(status, str) else None,
        "backend_name": backend_name if isinstance(backend_name, str) else None,
        "implementation_ref": implementation_ref if isinstance(implementation_ref, str) else None,
        "observed_at": _iso(record.source_timestamp),
    }


def _runtime_summary(record: AcesParticipantRuntimeRecordProjection) -> dict[str, Any]:
    """Reduce a participant-runtime projection to the response-safe shape."""
    payload = record.payload
    status = payload.get("status")
    status_reason = payload.get("status_reason")
    runtime_ref = payload.get("runtime_ref")
    return {
        "status": status if isinstance(status, str) else None,
        "status_reason": status_reason if isinstance(status_reason, str) else None,
        "runtime_ref": runtime_ref if isinstance(runtime_ref, str) else None,
        "observed_at": _iso(record.source_timestamp),
    }


def _latest_by_participant(
    records: list[AcesParticipantRuntimeRecordProjection],
) -> dict[str, AcesParticipantRuntimeRecordProjection]:
    """Reduce newest-first records to the latest row per ``participant_ref``."""
    latest: dict[str, AcesParticipantRuntimeRecordProjection] = {}
    for record in records:
        latest.setdefault(record.participant_ref, record)
    return latest


def _build_access_channels(request_id: UUID | str, instances: Iterable[InstanceContext]) -> list[RangeAccessChannel]:
    """Derive access channels as a pure function of the range's instances.

    Per-instance channels are looked up from ``ACCESS_CHANNELS_BY_OS_TYPE`` on
    the instance's canonical ``os_type``, so the projection advertises only
    channels actually openable for that target (Windows -> Guacamole RDP; Linux
    -> browser terminal + Guacamole range SSH; PAN-OS -> Guacamole NGFW SSH)
    rather than blanket-advertising every protocol by role. Instances with no
    uuid or an unrecognized ``os_type`` contribute no per-instance channels.
    Exactly one range-level backend-command channel is always appended, keyed
    by ``request_id``. This never queries live service state.
    """
    channels: list[RangeAccessChannel] = []
    for instance in instances:
        target_ref = instance.uuid
        if not target_ref:
            continue
        for channel in ACCESS_CHANNELS_BY_OS_TYPE.get(instance.os_type, ()):
            channels.append(RangeAccessChannel(channel=channel, target_ref=target_ref))
    channels.append(RangeAccessChannel(channel=ACCESS_CHANNEL_BACKEND_COMMAND, target_ref=str(request_id)))
    return channels


def build_range_participant_runtime_projection(
    request_id: UUID | str,
    instances: Iterable[InstanceContext],
    *,
    contract_profile: str = SHIFTER_BACKEND_PROFILE,
) -> RangeParticipantRuntimeProjection | None:
    """Build the compact participant/runtime projection for a range's ``request_id``.

    Reads the latest participant-implementation and participant-runtime rows
    through the #1288 read seam (:func:`list_participant_runtime_records`),
    groups them latest-first per ``participant_ref``, and pairs them with a
    pure access-channel derivation over ``instances``. Returns ``None`` when
    the range has zero participant rows of either kind (legacy / non-ACES
    ranges), so callers can treat the projection as absent -- mirrors
    :func:`build_range_aces_projection`.
    """
    implementation_records = list_participant_runtime_records(
        request_id,
        RECORD_KIND_PARTICIPANT_IMPLEMENTATION,
        limit=MAX_HISTORY_LIMIT,
        contract_profile=contract_profile,
    )
    runtime_records = list_participant_runtime_records(
        request_id,
        RECORD_KIND_PARTICIPANT_RUNTIME,
        limit=MAX_HISTORY_LIMIT,
        contract_profile=contract_profile,
    )
    if not implementation_records and not runtime_records:
        return None

    latest_implementation = _latest_by_participant(implementation_records)
    latest_runtime = _latest_by_participant(runtime_records)
    participant_refs = sorted(set(latest_implementation) | set(latest_runtime))

    participants = [
        RangeParticipantSummary(
            participant_ref=ref,
            implementation=_implementation_summary(latest_implementation[ref])
            if ref in latest_implementation
            else None,
            runtime=_runtime_summary(latest_runtime[ref]) if ref in latest_runtime else None,
        )
        for ref in participant_refs
    ]

    return RangeParticipantRuntimeProjection(
        participants=participants,
        access_channels=_build_access_channels(request_id, instances),
    )
