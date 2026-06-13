"""Mutation views for scenario editor actions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from cms.scenario_editor.services import (
    ScenarioEditorError,
    clone_scenario_from_form_post,
    delete_scenario,
    toggle_scenario_metadata_flag,
)
from cms.scenario_editor.view_support import (
    ERRORS_CONTEXT_KEY,
    SOURCE_CONTEXT_KEY,
    VIEW_RECOVERABLE_EXCEPTIONS,
    render_error_message,
    render_internal_error,
    render_not_found,
    render_unexpected_error,
)
from cms.scenarios.registry import get_scenario_detail
from shared.auth import threat_research_required
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

CLONE_TEMPLATE = "scenario_editor/clone.html"
DETAIL_ROUTE = "scenario_editor:detail"
LIST_ROUTE = "scenario_editor:list"


@dataclass(frozen=True)
class ToggleFlagSpec:
    field: str
    default: bool
    log_name: str
    on_message: str
    off_message: str


@threat_research_required
@require_POST
def scenario_delete_view(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Delete a custom scenario."""
    try:
        try:
            delete_scenario(cast("User", request.user), scenario_id)
        except ScenarioEditorError as e:
            return render_error_message(request, e.public_message)

        logger.info(
            "scenario_delete_view: deleted scenario_id=%s by user_id=%s",
            safe_log_value(scenario_id),
            request.user.id,
        )
        messages.success(request, "Scenario deleted successfully.")
        return redirect(LIST_ROUTE)
    except VIEW_RECOVERABLE_EXCEPTIONS:
        return render_unexpected_error(request, logger, "scenario_delete_view", scenario_id=scenario_id)


def _toggle_metadata_flag(request: HttpRequest, scenario_id: str, spec: ToggleFlagSpec) -> HttpResponse:
    try:
        new_value = toggle_scenario_metadata_flag(
            cast("User", request.user),
            scenario_id,
            field=spec.field,
            default=spec.default,
        )
    except ValueError:
        return render_not_found(request, logger, spec.log_name, scenario_id)
    except ScenarioEditorError as e:
        return render_error_message(request, e.public_message)
    except VIEW_RECOVERABLE_EXCEPTIONS:
        return render_unexpected_error(request, logger, spec.log_name, scenario_id=scenario_id)

    logger.info(
        "%s: toggled %s=%s for scenario_id=%s by user_id=%s",
        spec.log_name,
        spec.field,
        new_value,
        safe_log_value(scenario_id),
        request.user.id,
    )
    messages.success(request, spec.on_message if new_value else spec.off_message)
    return redirect(LIST_ROUTE)


@threat_research_required
@require_POST
def scenario_toggle_enabled(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Toggle enabled state for a scenario."""
    return _toggle_metadata_flag(
        request,
        scenario_id,
        ToggleFlagSpec(
            field="enabled",
            default=True,
            log_name="scenario_toggle_enabled",
            on_message="Scenario enabled successfully.",
            off_message="Scenario disabled successfully.",
        ),
    )


@threat_research_required
@require_POST
def scenario_toggle_staff_only(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Toggle staff_only state for a scenario."""
    return _toggle_metadata_flag(
        request,
        scenario_id,
        ToggleFlagSpec(
            field="staff_only",
            default=False,
            log_name="scenario_toggle_staff_only",
            on_message="Access set to staff only successfully.",
            off_message="Access set to all users successfully.",
        ),
    )


def _handle_clone_post(request: HttpRequest, scenario_id: str, source: dict[str, Any]) -> HttpResponse:
    scenario, new_name, errors = clone_scenario_from_form_post(cast("User", request.user), scenario_id, request.POST)
    if errors:
        return render(request, CLONE_TEMPLATE, {SOURCE_CONTEXT_KEY: source, ERRORS_CONTEXT_KEY: errors})

    if scenario is None:
        return render_internal_error(request, logger, "scenario_clone_view", scenario_id=scenario_id)
    logger.info(
        "scenario_clone_view: cloned scenario_id=%s to new_scenario_id=%s by user_id=%s",
        safe_log_value(scenario_id),
        safe_log_value(scenario.scenario_id),
        request.user.id,
    )
    messages.success(request, f"Scenario cloned as '{new_name or scenario.scenario_id}' successfully.")
    return redirect(DETAIL_ROUTE, scenario_id=scenario.scenario_id)


def _scenario_clone_view_impl(request: HttpRequest, scenario_id: str) -> HttpResponse:
    try:
        source = get_scenario_detail(scenario_id)
    except ValueError:
        return render_not_found(request, logger, "scenario_clone_view", scenario_id)
    if request.method == "GET":
        return render(request, CLONE_TEMPLATE, {SOURCE_CONTEXT_KEY: source})
    return _handle_clone_post(request, scenario_id, source)


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_clone_view(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Clone a scenario."""
    try:
        return _scenario_clone_view_impl(request, scenario_id)
    except VIEW_RECOVERABLE_EXCEPTIONS:
        return render_unexpected_error(request, logger, "scenario_clone_view", scenario_id=scenario_id)
