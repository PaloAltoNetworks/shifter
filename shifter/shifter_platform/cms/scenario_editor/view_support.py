"""Shared response helpers for scenario editor views."""

from __future__ import annotations

import logging
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from cms.scenarios.registry import get_scenario_detail, is_default_scenario
from shared.log_sanitize import safe_log_value

ERROR_TEMPLATE = "scenario_editor/error.html"
NOT_FOUND_TEMPLATE = "scenario_editor/not_found.html"


def render_unexpected_error(
    request: HttpRequest,
    logger: logging.Logger,
    log_name: str,
    *,
    scenario_id: str | None = None,
) -> HttpResponse:
    """Log an unexpected view failure and render the standard 500 page."""
    if scenario_id is None:
        logger.exception("%s: unexpected error for user_id=%s", log_name, request.user.id)
    else:
        logger.exception(
            "%s: unexpected error for user_id=%s, scenario_id=%s",
            log_name,
            request.user.id,
            safe_log_value(scenario_id),
        )
    return render(
        request,
        ERROR_TEMPLATE,
        {"message": "An unexpected error occurred. Please try again."},
        status=500,
    )


def render_not_found(request: HttpRequest, logger: logging.Logger, log_name: str, scenario_id: str) -> HttpResponse:
    logger.warning("%s: scenario not found scenario_id=%s", log_name, safe_log_value(scenario_id))
    return render(request, NOT_FOUND_TEMPLATE, {"scenario_id": scenario_id}, status=404)


def resolve_editable_scenario(
    request: HttpRequest,
    scenario_id: str,
    *,
    default_message: str,
    logger: logging.Logger,
    log_name: str,
) -> tuple[dict[str, Any] | None, HttpResponse | None]:
    """Return an editable scenario or an already-rendered 403/404 response."""
    if is_default_scenario(scenario_id):
        return None, render(request, ERROR_TEMPLATE, {"message": default_message}, status=403)
    try:
        return get_scenario_detail(scenario_id), None
    except ValueError:
        return None, render_not_found(request, logger, log_name, scenario_id)
