"""Organizer model-access event assessment (M09, #2126 / PLAT-202).

Event model-access *policy* (declared demand and source sponsorship) is already
managed through the organizer event write endpoint. This module adds the bounded
capacity **assessment** read: the safe planning summary an organizer sees, with
raw quotas, usage figures, and account identifiers kept operator-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import HasActiveCTFActor, HasCTFEventAdminAccess, _CtfApiError
from ctf.api.organizer._base import _resolve_owned_event
from ctf.enums import EventCapability
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api_tokens.permissions import require_scope
from shared.api_tokens.scopes import MODEL_ACCESS_EVENT_READ

if TYPE_CHECKING:
    from uuid import UUID


class EventModelAccessAssessmentSerializer(serializers.Serializer):
    """Bounded model-access capacity assessment for an event."""

    available = serializers.BooleanField()
    outcome = serializers.CharField(allow_null=True)
    blocking = serializers.BooleanField(allow_null=True)
    partition = serializers.CharField(allow_null=True)
    reason_codes = serializers.ListField(child=serializers.CharField())


class EventModelAccessAssessmentView(APIView):
    """Organizer read of an event's bounded model-access capacity assessment.

    Returns only the safe summary — outcome, whether it blocks, the partition and
    bounded reason codes. Raw quota limits, usage figures and account identifiers
    stay operator-only. A ``None`` assessment (model access disabled, no
    declaration, or the assessment itself unavailable) reports ``available:false``
    with empty fields, never a fabricated positive decision.
    """

    permission_classes = [
        IsAuthenticatedSessionOrApiToken,
        HasActiveCTFActor,
        HasCTFEventAdminAccess,
        require_scope(MODEL_ACCESS_EVENT_READ, MODEL_ACCESS_EVENT_READ),
    ]

    @extend_schema(responses=EventModelAccessAssessmentSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        from ctf.services.range.capacity import assess_declared_capacity

        try:
            _resolve_owned_event(request, event_id, capability=EventCapability.RANGES)
        except _CtfApiError as exc:
            return exc.to_response(request)
        summary = assess_declared_capacity(event_id, source="organizer-management")
        if summary is None:
            return Response(
                {"available": False, "outcome": None, "blocking": None, "partition": None, "reason_codes": []}
            )
        return Response({"available": True, **summary})
