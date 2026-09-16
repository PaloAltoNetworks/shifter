"""Read-only Mission Control APIs for RAES participant-runtime sidecar projections (#1288).

Exposes participant-implementation and participant-runtime records for a
range, keyed by the Shifter ``request_id``. Mirrors
``mission_control.api.raes`` (the incumbent operation-record read API from
#1275). Each endpoint:

- reuses the authenticated ``MissionControlReadAPIView`` gate
  (``IsAuthenticatedSessionOrApiToken`` + ``HasMissionControlActor`` + exact
  ``MISSION_CONTROL_RANGE_READ`` scope);
- authorizes range ownership through ``cms.services.get_range_by_request_id``
  **before** any sidecar lookup, so a not-owned or unknown ``request_id`` is a
  404 with no enumeration signal;
- returns redacted projections from the shared read seam
  (``shared.raes.participant_runtime_projections``); it never serializes the
  raw sidecar payload.

Record-kind vocabulary is read through the shared seam constants, not
``shared.models`` (ADR-001-R2 cross-layer rule).
"""

from __future__ import annotations

from uuid import UUID

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.request import Request
from rest_framework.response import Response

from cms.services import get_range_by_request_id
from mission_control.api._base import MissionControlReadAPIView, _validated
from mission_control.api.serializers import (
    RaesParticipantRecordQuerySerializer,
    RaesParticipantRuntimeRecordListResponseSerializer,
    RaesParticipantRuntimeRecordSerializer,
)
from shared.exceptions import CMSError
from shared.raes.participant_runtime_projections import (
    RECORD_KIND_PARTICIPANT_IMPLEMENTATION,
    RECORD_KIND_PARTICIPANT_RUNTIME,
    list_participant_runtime_records,
)


class _RaesParticipantRecordListView(MissionControlReadAPIView):
    """Base read view returning one participant-runtime record kind's redacted projections."""

    #: Subclasses set this to an ``RaesParticipantRuntimeRecord.RecordKind`` value.
    record_kind: str

    def get(self, request: Request, request_id: UUID) -> Response:
        """Return newest-first redacted records for the owned range's request_id."""
        actor = self.actor_user()
        # Authorize BEFORE touching the sidecar. Not-owned and unknown both 404.
        try:
            get_range_by_request_id(actor, str(request_id))
        except CMSError:
            return self.not_found("Range not found")

        params, error = _validated(self, RaesParticipantRecordQuerySerializer, request.query_params)
        if error is not None:
            return error
        assert params is not None

        records = list_participant_runtime_records(
            request_id,
            self.record_kind,
            limit=params["limit"],
            participant_ref=params.get("participant_ref"),
        )
        serializer = RaesParticipantRuntimeRecordSerializer(records, many=True)
        return Response(
            {
                "request_id": str(request_id),
                "record_kind": self.record_kind,
                "results": serializer.data,
            }
        )


@extend_schema_view(
    get=extend_schema(
        responses=RaesParticipantRuntimeRecordListResponseSerializer,
        operation_id="api_v1_mission_control_raes_participant_implementations_list",
    )
)
class RaesParticipantImplementationListView(_RaesParticipantRecordListView):
    """``GET`` RAES participant-implementation records for a range."""

    record_kind = RECORD_KIND_PARTICIPANT_IMPLEMENTATION


@extend_schema_view(
    get=extend_schema(
        responses=RaesParticipantRuntimeRecordListResponseSerializer,
        operation_id="api_v1_mission_control_raes_participant_runtimes_list",
    )
)
class RaesParticipantRuntimeListView(_RaesParticipantRecordListView):
    """``GET`` RAES participant-runtime records for a range."""

    record_kind = RECORD_KIND_PARTICIPANT_RUNTIME
