"""Mission Control range-history API projection."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from cms.services import list_mission_control_range_history
from mission_control.api._base import MissionControlReadAPIView
from mission_control.api.serializers import RangeHistoryResponseSerializer, RangeHistorySerializer


class RangeHistoryView(MissionControlReadAPIView):
    """Return the authenticated user's range history (#1370).

    The product-scoped query includes soft-deleted terminal ranges and excludes
    CTF-sourced ranges. Raw rows are projected explicitly because history has no
    hydrated instances, agent name, or computed-status fields.
    """

    @extend_schema(responses=RangeHistoryResponseSerializer, operation_id="api_v1_mission_control_ranges_list")
    def get(self, request: Request) -> Response:
        """Return the authenticated actor's Mission Control range history, newest first."""
        ranges = list_mission_control_range_history(self.actor_user())
        serializer = RangeHistorySerializer(
            [
                {
                    "request_id": range_instance.request.request_id if range_instance.request else None,
                    "range_id": range_instance.range_id,
                    "scenario_id": range_instance.scenario_id,
                    "status": range_instance.status,
                    "range_source": range_instance.range_source,
                    "created_at": range_instance.created_at,
                    "updated_at": range_instance.updated_at,
                    "deleted_at": range_instance.deleted_at,
                }
                for range_instance in ranges
            ],
            many=True,
        )
        return Response({"ranges": serializer.data})
