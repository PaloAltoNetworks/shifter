"""Shared response helpers for scenario editor views."""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from cms.scenarios.registry import get_scenario_detail, is_default_scenario
from shared.log_sanitize import safe_log_value

ERROR_TEMPLATE = "scenario_editor/error.html"
NOT_FOUND_TEMPLATE = "scenario_editor/not_found.html"
ERRORS_CONTEXT_KEY = "errors"
MESSAGE_CONTEXT_KEY = "message"
MODE_CONTEXT_KEY = "mode"
SCENARIO_CONTEXT_KEY = "scenario"
SCENARIO_ID_CONTEXT_KEY = "scenario_id"
SOURCE_CONTEXT_KEY = "source"
UNEXPECTED_ERROR_MESSAGE = "An unexpected error occurred. Please try again."
YAML_CONTENT_CONTEXT_KEY = "yaml_content"
VIEW_RECOVERABLE_EXCEPTIONS = (
    AttributeError,
    DatabaseError,
    DjangoValidationError,
    KeyError,
    RuntimeError,
    TypeError,
)


def render_error_message(request: HttpRequest, message: str, *, status: int = 200) -> HttpResponse:
    return render(request, ERROR_TEMPLATE, {MESSAGE_CONTEXT_KEY: message}, status=status)


def render_internal_error(
    request: HttpRequest,
    logger: logging.Logger,
    log_name: str,
    *,
    scenario_id: str | None = None,
) -> HttpResponse:
    """Log an impossible view state and render the standard 500 page."""
    if scenario_id is None:
        logger.error("%s: unexpected internal state for user_id=%s", log_name, request.user.id)
    else:
        logger.error(
            "%s: unexpected internal state for user_id=%s, scenario_id=%s",
            log_name,
            request.user.id,
            safe_log_value(scenario_id),
        )
    return render_error_message(request, UNEXPECTED_ERROR_MESSAGE, status=500)


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
    return render_error_message(request, UNEXPECTED_ERROR_MESSAGE, status=500)


def render_not_found(request: HttpRequest, logger: logging.Logger, log_name: str, scenario_id: str) -> HttpResponse:
    logger.warning("%s: scenario not found scenario_id=%s", log_name, safe_log_value(scenario_id))
    return render(request, NOT_FOUND_TEMPLATE, {SCENARIO_ID_CONTEXT_KEY: scenario_id}, status=404)


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
        return None, render_error_message(request, default_message, status=403)
    try:
        return get_scenario_detail(scenario_id), None
    except ValueError:
        return None, render_not_found(request, logger, log_name, scenario_id)
