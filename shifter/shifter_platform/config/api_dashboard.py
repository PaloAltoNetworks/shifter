"""Dashboard summary read for the SPA home/dashboard surface (#1369).

The platform shell's first authenticated screen is a role-aware operational
dashboard. It needs a small, bounded summary that composes existing readable
domain facts across apps (active range and active CTF event).
That composition is inherently cross-app, so it lives at the ``config``
composition root rather than in ``shared`` (which may not import ``cms``/``ctf``
services under ADR-001) or in any single app layer (none may import both).

The payload summarizes existing state only: it invents no new durable workflow
state, contains no secrets/tokens/cookies/user-entered content, and every field
fails closed on error so a degraded dependency never breaks the dashboard.
Authorization stays with the underlying resource endpoints; the counts here are
gated by the same advisory access checks the shell already uses.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.api_tokens.models import ApiToken

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from django.contrib.auth.models import User


class DashboardRangeSerializer(serializers.Serializer):
    """Bounded active-range summary."""

    present = serializers.BooleanField()
    status = serializers.CharField(allow_null=True, allow_blank=True)


class DashboardEventSerializer(serializers.Serializer):
    """Bounded active-event summary."""

    present = serializers.BooleanField()
    name = serializers.CharField(allow_null=True, allow_blank=True)


class DashboardSummarySerializer(serializers.Serializer):
    """Top-level dashboard summary payload."""

    active_range = DashboardRangeSerializer()
    active_event = DashboardEventSerializer()


def _range_summary(user: User | None) -> dict[str, object]:
    """Return a bounded active-range summary, failing closed on any error."""
    range_context = None
    if user is not None:
        try:
            from cms.services import get_active_range

            range_context = get_active_range(user)
        except Exception:
            logger.exception("dashboard summary: active-range lookup failed")
            range_context = None
    if range_context is None:
        return {"present": False, "status": None}
    return {"present": True, "status": str(range_context.status)}


def _event_summary(user: User | None) -> dict[str, object]:
    """Return a bounded active-event summary, failing closed on any error.

    Consumes the public ``ctf.services`` facade rather than the CTF-owned
    outbound ``ctf.bridges`` module (ADR-001, #1523).
    """
    if user is None:
        return {"present": False, "name": None}
    try:
        from ctf.services import active_event_summary

        return active_event_summary(user)
    except Exception:
        logger.exception("dashboard summary: active-event lookup failed")
        return {"present": False, "name": None}


class DashboardSummaryView(APIView):
    """Return the bounded operational dashboard summary for the SPA home."""

    authentication_classes = [ApiTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticatedSessionOrApiToken]

    @extend_schema(responses=DashboardSummarySerializer, operation_id="api_v1_dashboard_summary_retrieve")
    def get(self, request: Request) -> Response:
        # Session principals expose the active range/event; token principals are
        # programmatic and carry no session-scoped active context.
        auth = getattr(request, "auth", None)
        session_user = None if isinstance(auth, ApiToken) else request.user
        payload = {
            "active_range": _range_summary(session_user),
            "active_event": _event_summary(session_user),
        }
        return Response(DashboardSummarySerializer(payload).data)
