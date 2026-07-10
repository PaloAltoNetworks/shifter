"""Read-only Mission Control APIs for ACES operation sidecar projections (#1275).

Exposes operation status, operation receipts, and runtime snapshots for a
range, keyed by the Shifter ``request_id``. Each endpoint:

- reuses the authenticated ``MissionControlReadAPIView`` gate
  (``IsAuthenticatedSessionOrApiToken`` + ``HasMissionControlActor`` + exact
  ``MISSION_CONTROL_RANGE_READ`` scope);
- authorizes range ownership through ``cms.services.get_range_by_request_id``
  **before** any sidecar lookup, so a not-owned or unknown ``request_id`` is a
  404 with no enumeration signal;
- returns redacted projections from the shared read seam
  (``shared.aces.projections``); it never serializes the raw sidecar payload.

Record-kind vocabulary is read through the shared seam constants, not
``shared.models`` (ADR-001-R2 cross-layer rule).
"""

from __future__ import annotations

from uuid import UUID

from rest_framework.request import Request
from rest_framework.response import Response

from cms.services import get_range_by_request_id
from mission_control.api._base import MissionControlReadAPIView, _validated
from mission_control.api.serializers import AcesOperationRecordSerializer, AcesRecordQuerySerializer
from shared.aces.projections import (
    RECORD_KIND_OPERATION_RECEIPT,
    RECORD_KIND_OPERATION_STATUS,
    RECORD_KIND_RUNTIME_SNAPSHOT,
    list_operation_records,
)
from shared.exceptions import CMSError


class _AcesRecordListView(MissionControlReadAPIView):
    """Base read view returning one record kind's redacted projections."""

    #: Subclasses set this to an ``AcesOperationRecord.RecordKind`` value.
    record_kind: str

    def get(self, request: Request, request_id: UUID) -> Response:
        """Return newest-first redacted records for the owned range's request_id."""
        actor = self.actor_user()
        # Authorize BEFORE touching the sidecar. Not-owned and unknown both 404.
        try:
            get_range_by_request_id(actor, str(request_id))
        except CMSError:
            return self.not_found("Range not found")

        params, error = _validated(self, AcesRecordQuerySerializer, request.query_params)
        if error is not None:
            return error
        assert params is not None

        records = list_operation_records(request_id, self.record_kind, limit=params["limit"])
        serializer = AcesOperationRecordSerializer(records, many=True)
        return Response(
            {
                "request_id": str(request_id),
                "record_kind": self.record_kind,
                "results": serializer.data,
            }
        )


class AcesOperationStatusListView(_AcesRecordListView):
    """``GET`` ACES operation-status observations for a range."""

    record_kind = RECORD_KIND_OPERATION_STATUS


class AcesOperationReceiptListView(_AcesRecordListView):
    """``GET`` ACES operation receipts for a range."""

    record_kind = RECORD_KIND_OPERATION_RECEIPT


class AcesRuntimeSnapshotListView(_AcesRecordListView):
    """``GET`` ACES runtime snapshots for a range."""

    record_kind = RECORD_KIND_RUNTIME_SNAPSHOT
