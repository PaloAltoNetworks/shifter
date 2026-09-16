"""Read-only Mission Control APIs for RAES operation sidecar projections (#1275).

Exposes operation status, operation receipts, and runtime snapshots for a
range, keyed by the Shifter ``request_id``. Each endpoint:

- reuses the authenticated ``MissionControlReadAPIView`` gate
  (``IsAuthenticatedSessionOrApiToken`` + ``HasMissionControlActor`` + exact
  ``MISSION_CONTROL_RANGE_READ`` scope);
- authorizes range ownership through ``cms.services.get_range_by_request_id``
  **before** any sidecar lookup, so a not-owned or unknown ``request_id`` is a
  404 with no enumeration signal;
- returns redacted projections from the shared read seam
  (``shared.raes.projections``); it never serializes the raw sidecar payload.

Record-kind vocabulary is read through the shared seam constants, not
``shared.models`` (ADR-001-R2 cross-layer rule).
"""

from __future__ import annotations

from uuid import UUID

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.request import Request
from rest_framework.response import Response

from cms.services import get_range_by_request_id, project_range_cleanup_outcome
from mission_control.api._base import MissionControlReadAPIView, _validated
from mission_control.api.serializers import (
    RaesOperationRecordListResponseSerializer,
    RaesOperationRecordSerializer,
    RaesRecordQuerySerializer,
    RangeCleanupOutcomeResponseSerializer,
)
from shared.exceptions import CMSError
from shared.raes.projections import (
    RECORD_KIND_OPERATION_RECEIPT,
    RECORD_KIND_OPERATION_STATUS,
    RECORD_KIND_RUNTIME_SNAPSHOT,
    list_operation_records,
)


class _RaesRecordListView(MissionControlReadAPIView):
    """Base read view returning one record kind's redacted projections."""

    #: Subclasses set this to an ``RaesOperationRecord.RecordKind`` value.
    record_kind: str

    def get(self, request: Request, request_id: UUID) -> Response:
        """Return newest-first redacted records for the owned range's request_id."""
        actor = self.actor_user()
        # Authorize BEFORE touching the sidecar. Not-owned and unknown both 404.
        try:
            get_range_by_request_id(actor, str(request_id))
        except CMSError:
            return self.not_found("Range not found")

        params, error = _validated(self, RaesRecordQuerySerializer, request.query_params)
        if error is not None:
            return error
        assert params is not None

        records = list_operation_records(request_id, self.record_kind, limit=params["limit"])
        serializer = RaesOperationRecordSerializer(records, many=True)
        return Response(
            {
                "request_id": str(request_id),
                "record_kind": self.record_kind,
                "results": serializer.data,
            }
        )


@extend_schema_view(
    get=extend_schema(
        responses=RaesOperationRecordListResponseSerializer,
        operation_id="api_v1_mission_control_raes_operation_status_list",
    )
)
class RaesOperationStatusListView(_RaesRecordListView):
    """``GET`` RAES operation-status observations for a range."""

    record_kind = RECORD_KIND_OPERATION_STATUS


@extend_schema_view(
    get=extend_schema(
        responses=RaesOperationRecordListResponseSerializer,
        operation_id="api_v1_mission_control_raes_operation_receipts_list",
    )
)
class RaesOperationReceiptListView(_RaesRecordListView):
    """``GET`` RAES operation receipts for a range."""

    record_kind = RECORD_KIND_OPERATION_RECEIPT


@extend_schema_view(
    get=extend_schema(
        responses=RaesOperationRecordListResponseSerializer,
        operation_id="api_v1_mission_control_raes_runtime_snapshots_list",
    )
)
class RaesRuntimeSnapshotListView(_RaesRecordListView):
    """``GET`` RAES runtime snapshots for a range."""

    record_kind = RECORD_KIND_RUNTIME_SNAPSHOT


class RangeCleanupOutcomeView(MissionControlReadAPIView):
    """``GET`` the truthful cleanup outcome for a range (#2086, ADR-063-R4).

    Authorizes range ownership before disclosing anything (a not-owned or unknown
    request_id is an opaque 404), then reports the distinct cleanup facts and any
    retained residual obligations from durable state.
    """

    @extend_schema(
        responses=RangeCleanupOutcomeResponseSerializer,
        operation_id="api_v1_mission_control_range_cleanup_outcome",
    )
    def get(self, request: Request, request_id: UUID) -> Response:
        """Return the cleanup outcome for the owned range's request_id."""
        actor = self.actor_user()
        try:
            # Terminal-aware: the cleanup surface must authorize and report on
            # DESTROYED/FAILED ranges, not 404 the terminal outcomes it advertises.
            get_range_by_request_id(actor, str(request_id), include_terminal=True)
        except CMSError:
            return self.not_found("Range not found")

        outcome = project_range_cleanup_outcome(request_id)
        return Response(
            {
                "request_id": str(request_id),
                "found": outcome.found,
                "operation_status": outcome.operation_status,
                "dispatch_status": outcome.dispatch_status,
                "cancel_state": outcome.cancel_state,
                "cleanup": outcome.cleanup,
                "residual_obligations": [
                    {"code": obligation.code, "detail": obligation.detail}
                    for obligation in outcome.residual_obligations
                ],
                "verification_observed_at": outcome.verification_observed_at,
                "verification_scope": outcome.verification_scope,
            }
        )
