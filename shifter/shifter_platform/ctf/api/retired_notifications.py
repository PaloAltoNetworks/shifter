"""Explicitly retired notification writes (ADR-065); no dispatch compatibility."""

from __future__ import annotations

from django.http import HttpRequest
from rest_framework.request import Request
from rest_framework.response import Response

from shared.api.errors import api_error_response


def retired_notification_response(request: Request | HttpRequest) -> Response:
    """Return the bounded retirement response for obsolete write routes."""

    return api_error_response(
        code="ctf_notification_retired",
        message="Legacy notification writes are retired. Use /api/v1/ctf/communications/.",
        status_code=410,
        request=request,
    )
